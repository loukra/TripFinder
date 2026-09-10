"""Agentic Source Discovery (plan §4.6 step 3): a bounded multi-search loop
through the source tool boundary (plan §3.1).

The LLM proposes one query per turn; everything that bounds the loop is
deterministic. Three guarantees, each load-bearing for the acceptance
criteria in plan §10 Phase 6:

* the loop never issues more than ``budget.max_search_queries`` searches;
* a query that is a near-duplicate of one already searched is never sent
  to the source — the turn is spent, but no search call is wasted;
* the loop still terminates even if the LLM keeps proposing duplicates,
  because a run of unproductive turns aborts discovery early.
"""

from __future__ import annotations

import re

from tripfinder.analysis.discovery import DiscoveryTurnResponse, build_discovery_prompt
from tripfinder.domain.models import ResearchPlan, ResearchStatus, SourceDocument
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.health import get_recorder
from tripfinder.sources.failures import UNKNOWN_FAILURE_KIND
from tripfinder.sources.tools import SourceSearchTool

_DUPLICATE_JACCARD_THRESHOLD = 0.7
_MAX_CONSECUTIVE_DUPLICATE_TURNS = 3

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


class AgenticDiscoveryStep:
    """Real implementation of plan §4.6 step 3 (stands in for `FakeDiscoveryStep`)."""

    name = "agentic_discovery"

    async def run(self, context: PipelineContext) -> PipelineContext:
        plan: ResearchPlan = context.data["plan"]
        budget = context.research.research_config.budget
        tool = SourceSearchTool(context.source, limit_per_query=budget.max_posts_per_query)

        issued_queries: list[str] = []
        documents: dict[str, SourceDocument] = {}
        consecutive_duplicate_turns = 0
        # Discovery searches are source calls like any other, so they count
        # toward the §8.1 accounting the health assessment reads later.
        recorder = get_recorder(context)

        while len(issued_queries) < budget.max_search_queries:
            turn = await context.llm.complete_structured(
                prompt=build_discovery_prompt(
                    plan, issued_queries=issued_queries, documents_found=len(documents)
                ),
                response_model=DiscoveryTurnResponse,
            )

            if not turn.should_continue or not turn.next_query:
                break

            if _is_near_duplicate(turn.next_query, issued_queries):
                consecutive_duplicate_turns += 1
                if consecutive_duplicate_turns >= _MAX_CONSECUTIVE_DUPLICATE_TURNS:
                    break
                continue

            consecutive_duplicate_turns = 0
            result = await tool.search(turn.next_query)
            issued_queries.append(turn.next_query)
            if result.ok:
                recorder.record_success(context.source.name)
            else:
                recorder.record_failure(
                    context.source.name, kind=result.failure_kind or UNKNOWN_FAILURE_KIND
                )
            for document in result.documents:
                documents[document.id] = document

        context.data["documents"] = list(documents.values())
        context.data["discovery_queries_issued"] = issued_queries
        context.research.status = ResearchStatus.RETRIEVING
        return context
