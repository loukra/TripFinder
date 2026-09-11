"""Agentic Source Discovery (plan §4.6 step 3, rebuilt on web search by §2.11).

Two halves, in order:

1. **Find addresses.** The LLM proposes a batch of plain-language queries
   per turn; the tool boundary restricts each to Reddit, runs them
   **concurrently**, and returns post ids. One query per turn made the model
   the serial part of a concurrent pipeline — a measured run analysed 2153
   of 4417 admitted comments, with roughly two thirds of the analysis
   window idle, waiting for documents nobody had searched for yet.
2. **Hydrate them.** One batched call to the source adapter turns the
   collected ids into real ``SourceDocument``s.

Everything that bounds the loop is deterministic. Four guarantees, each
load-bearing for plan §10 Phase 6 and Phase 14.5 acceptance:

* the loop never issues more than ``budget.max_search_queries`` searches;
* a query that is a near-duplicate of one already searched is never sent;
* the loop still terminates even if the LLM keeps proposing unproductive
  turns, because a run of them aborts discovery early;
* both external services are recorded separately in §8.1 health accounting,
  so a run that found nothing because search was down is distinguishable
  from one that searched properly and found little (plan §0.1).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

from tripfinder.analysis.discovery import DiscoveryTurnResponse, build_discovery_prompt
from tripfinder.domain.models import (
    ResearchFlag,
    ResearchPlan,
    ResearchStatus,
    SourceDocument,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.deadline import admission_deadline
from tripfinder.pipeline.health import get_recorder
from tripfinder.search.tools import RedditThreadSearchTool
from tripfinder.sources.failures import UNKNOWN_FAILURE_KIND, failure_kind

logger = logging.getLogger(__name__)

_DUPLICATE_JACCARD_THRESHOLD = 0.7
_MAX_CONSECUTIVE_UNPRODUCTIVE_TURNS = 3

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenize(query: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(query.lower()))


def _is_near_duplicate(candidate: str, issued_queries: list[str]) -> bool:
    """Cheapest-first token-overlap check (plan §10 Phase 6 acceptance)."""
    candidate_tokens = _tokenize(candidate)
    if not candidate_tokens:
        return True  # a query with nothing to search on is never worth a call
    for prior in issued_queries:
        prior_tokens = _tokenize(prior)
        if not prior_tokens:
            continue
        overlap = len(candidate_tokens & prior_tokens)
        union = len(candidate_tokens | prior_tokens)
        if union and overlap / union >= _DUPLICATE_JACCARD_THRESHOLD:
            return True
    return False



async def discover_documents(
    context: PipelineContext,
) -> AsyncIterator[Sequence[SourceDocument]]:
    """The discovery loop, publishing each turn's documents as it finds them.

    One implementation, two callers (plan §2.14.2). The loop is unchanged and
    still bounded by every guarantee above; what changed is **when** its
    output becomes available. Hydration now happens per turn rather than once
    at the end, which costs a few more source calls — each recorded
    separately, as §8.1 requires — and buys the thing 14.8 exists for: a
    document can be triaged, fetched and analysed while the loop is still
    proposing its next query.

    §2.12.3 measured why that matters. Discovery was 56.6 s of a 282.5 s run,
    fully sequential, and not one downstream step could begin until all of it
    had finished.
    """
    plan: ResearchPlan = context.data["plan"]
    budget = context.research.research_config.budget
    tool = RedditThreadSearchTool(context.search, limit_per_query=budget.max_posts_per_query)
    # Discovery calls two external services, and §8.1 accounts for each
    # under its own name — the aggregate is what the floors are applied
    # to, but the snapshot has to say which one failed.
    recorder = get_recorder(context)

    per_turn = max(1, budget.search_queries_per_turn)
    issued_queries: list[str] = []
    post_ids: list[str] = []
    documents: list[SourceDocument] = []
    consecutive_unproductive_turns = 0
    context.data["documents"] = documents
    context.data["discovery_queries_issued"] = issued_queries
    context.data["discovery_post_ids_found"] = post_ids
    context.data["discovery_documents_unhydrated"] = 0

    deadline = admission_deadline(context)
    while len(issued_queries) < budget.max_search_queries:
        # A document found after the last analysis call may be admitted is a
        # document nothing will read. Discovery is the run's second-largest
        # cost (§2.12.3: 56.6 s of 282.5 s), so searching past the point of
        # usefulness is money spent on evidence that cannot reach the
        # number. What is already in flight still finishes.
        if deadline is not None and datetime.now(UTC) > deadline:
            context.research.diagnostics.record_suppression(
                step="agentic_discovery",
                reason=SuppressionReason.BUDGET_MAX_SEARCH_QUERIES,
                count=budget.max_search_queries - len(issued_queries),
                detail="searches never issued — the dispatch deadline had passed",
            )
            context.research.diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)
            break

        polling_found, topical_found = _triage_tally(context)
        turn = await context.llm.complete_structured(
            prompt=build_discovery_prompt(
                plan,
                issued_queries=issued_queries,
                documents_found=len(post_ids),
                queries_per_turn=min(per_turn, budget.max_search_queries - len(issued_queries)),
                polling_found=polling_found,
                topical_found=topical_found,
            ),
            response_model=DiscoveryTurnResponse,
        )

        if not turn.should_continue or not turn.next_queries:
            break

        # Every guarantee the one-query loop gave still holds, and each is
        # now applied across the batch as well as against history: the
        # search cap counts queries, not turns, and two queries proposed in
        # the same breath can be near-duplicates of each other.
        room = budget.max_search_queries - len(issued_queries)
        batch: list[str] = []
        for candidate in turn.next_queries:
            if len(batch) >= room:
                break
            if _is_near_duplicate(candidate, [*issued_queries, *batch]):
                continue
            batch.append(candidate)

        if not batch:
            consecutive_unproductive_turns += 1
            if consecutive_unproductive_turns >= _MAX_CONSECUTIVE_UNPRODUCTIVE_TURNS:
                break
            continue

        consecutive_unproductive_turns = 0
        results = await asyncio.gather(*(tool.search(query) for query in batch))
        issued_queries.extend(batch)
        for result in results:
            if result.ok:
                recorder.record_success(context.search.name)
            else:
                recorder.record_failure(
                    context.search.name, kind=result.failure_kind or UNKNOWN_FAILURE_KIND
                )

        fresh: list[str] = []
        for post_id in (post_id for result in results for post_id in result.post_ids):
            if post_id not in post_ids and len(post_ids) < budget.max_total_posts:
                post_ids.append(post_id)
                fresh.append(post_id)

        if fresh:
            hydrated = await _hydrate(context, fresh)
            documents.extend(hydrated)
            # Plan §0.1: the gap between ids found and documents hydrated is
            # evidence we located and failed to retrieve. It is recorded
            # rather than left to be inferred from a shorter-than-expected
            # list.
            context.data["discovery_documents_unhydrated"] = len(post_ids) - len(documents)
            if hydrated:
                yield hydrated

        if len(post_ids) >= budget.max_total_posts:
            break


class AgenticDiscoveryStep:
    """Real implementation of plan §4.6 step 3 (stands in for `FakeDiscoveryStep`)."""

    name = "agentic_discovery"

    async def run(self, context: PipelineContext) -> PipelineContext:
        """The whole loop, drained before anything downstream begins."""
        async for _ in discover_documents(context):
            pass
        context.research.status = ResearchStatus.RETRIEVING
        return context


def _triage_tally(context: PipelineContext) -> tuple[int, int]:
    """How the threads found so far were classified, if anything has been.

    Discovery and triage run concurrently (§2.14.2), so this is a reading of
    a number that is still moving — which is exactly what makes it useful
    to the next turn, and why nothing downstream is derived from it.
    """
    tally = context.data.get("triage_tally")
    if not isinstance(tally, dict):
        return 0, 0
    return int(tally.get("polling", 0)), int(tally.get("topical", 0))


async def _hydrate(context: PipelineContext, post_ids: Sequence[str]) -> list[SourceDocument]:
    """Turn collected ids into documents, in one batched source call.

    A hydration failure is recorded, not raised: §8.1 decides what an
    unreachable source means for the run as a whole, and it cannot do
    that if this step crashes first.
    """
    if not post_ids:
        return []

    recorder = get_recorder(context)
    try:
        documents = list(await context.source.fetch_documents(post_ids))
    except Exception as exc:
        logger.warning("discovery: hydrating %d post(s) failed: %s", len(post_ids), exc)
        recorder.record_failure(context.source.name, kind=failure_kind(exc))
        return []
    recorder.record_success(context.source.name)
    return documents
