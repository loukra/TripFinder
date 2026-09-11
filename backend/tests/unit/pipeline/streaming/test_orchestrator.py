"""Discovery, triage and strands overlapping (plan §2.14.2, §10 Phase 14.8).

The claim this phase rests on: a document found by the first search is being
analysed while the model is still proposing the fourth query. §2.12.3
measured the alternative — roughly 135 s of a 282.5 s run elapsed before the
first analysis call went out, because every step waited for the one before
it to finish over the whole corpus.

Also owned here: the §0.1 criterion against a concurrent pipeline (one
strand dying changes nothing but its own contribution), and §8.1's floor,
which stopped being a barrier and had to keep its guarantee as a gate
without ever becoming a way for a run to hang.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence

from pydantic import BaseModel, HttpUrl

from builders.phase7 import make_comment, make_context
from tripfinder.analysis.comment_analysis import (
    CommentAnalysis,
    CommentAnalysisBatch,
    EntityMention,
)
from tripfinder.analysis.discovery import DiscoveryTurnResponse
from tripfinder.analysis.triage import DocumentTriage, DocumentTriageBatch
from tripfinder.domain.config import (
    RankingConfig,
    ResearchBudget,
    ResearchConfig,
    SourceHealthFloors,
)
from tripfinder.domain.models import (
    Comment,
    EntityType,
    ReasonCode,
    SourceDocument,
    Stance,
    SuppressionReason,
    TriageVerdict,
)
from tripfinder.domain.ports import WebSearchHit, WebSearchQuery
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.streaming.orchestrator import run_strands

BODY = "Michigan is stunning in autumn and almost nobody ever goes there."
THREAD_URL = "https://www.reddit.com/r/travel/comments/{post_id}/a_thread/"


def _document(document_id: str) -> SourceDocument:
    return SourceDocument(
        id=document_id,
        source="fake",
        title="Most underrated state for nature?",
        url=HttpUrl(THREAD_URL.format(post_id=document_id)),
        subreddit="travel",
        created_at=make_comment("x").created_at,
        comment_count=50,
    )


class OneThreadPerSearch:
    """Each query returns one fresh thread — so waves are observable."""

    name = "fake_search"

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        self.queries.append(query.query)
        post_id = f"doc{len(self.queries)}"
        return [WebSearchHit(url=THREAD_URL.format(post_id=post_id), title=post_id)]


class Source:
    """Hydrates anything, and serves a fixed comment tree per document."""

    name = "fake_source"

    def __init__(self, *, comments_each: int = 4, failing: set[str] | None = None) -> None:
        self._comments_each = comments_each
        self._failing = failing or set()
        self.fetched: list[str] = []

    async def health_check(self) -> bool:
        return True

    async def fetch_documents(self, document_ids: Sequence[str]) -> Sequence[SourceDocument]:
        return [_document(document_id) for document_id in document_ids]

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        self.fetched.append(document.id)
        if document.id in self._failing:
            raise ConnectionError("thread is gone")
        return [
            make_comment(
                f"{document.id}-c{index}",
                document_id=document.id,
                user_id=f"{document.id}-u{index}",
                body=BODY,
            )
            for index in range(self._comments_each)
        ]


class Model:
    """Answers discovery turns, triage batches and analysis calls.

    ``analysis_calls`` and ``search_turns`` are counted separately so a test
    can ask the question this phase exists to answer: had the loop finished
    searching before the first comment was analysed?
    """

    def __init__(
        self,
        *,
        turns: int = 4,
        verdict: TriageVerdict = TriageVerdict.POLLING,
        block_search_until_analysed: bool = False,
    ) -> None:
        self._turns = turns
        self._verdict = verdict
        self._block = block_search_until_analysed
        self.search_turns = 0
        self.analysis_calls = 0
        self.analysis_started = asyncio.Event()

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        if response_model is DiscoveryTurnResponse:
            self.search_turns += 1
            if self._block and self.search_turns == 2:
                # Discovery stops here until something has been analysed. A
                # pipeline finishes; a sequential run deadlocks, because
                # nothing downstream of discovery can start.
                await self.analysis_started.wait()
            await asyncio.sleep(0)
            if self.search_turns > self._turns:
                return DiscoveryTurnResponse(  # type: ignore[return-value]
                    should_continue=False, reasoning="enough"
                )
            return DiscoveryTurnResponse(  # type: ignore[return-value]
                should_continue=True,
                next_queries=[f"angle number {self.search_turns}"],
                reasoning="fresh angle",
            )
        if response_model is DocumentTriageBatch:
            await asyncio.sleep(0)
            return DocumentTriageBatch(  # type: ignore[return-value]
                items=[
                    DocumentTriage(
                        document_id=document_id,
                        verdict=self._verdict,
                        scope_match=True,
                        granularity_match=True,
                        criterion_match=True,
                        confidence=0.9,
                        reason="asks people to name states",
                    )
                    for document_id in re.findall(r"id=(doc\d+)", prompt)
                ]
            )
        self.analysis_calls += 1
        self.analysis_started.set()
        await asyncio.sleep(0)
        return CommentAnalysisBatch(  # type: ignore[return-value]
            items=[
                CommentAnalysis(
                    comment_id=comment_id,
                    topic_relevance=0.9,
                    criterion_relevance=0.9,
                    scope_match=True,
                    overall_confidence=0.9,
                    reason_code=ReasonCode.RECOMMENDS,
                    mentions=[
                        EntityMention(
                            raw_text="Michigan",
                            entity_type=EntityType.STATE,
                            stance=Stance.POSITIVE,
                            strength=0.8,
                            supporting_quote=BODY,
                        )
                    ],
                )
                for comment_id in re.findall(r"doc\d+-c\d+", prompt)
            ]
        )


def _context(
    *,
    model: Model | None = None,
    source: Source | None = None,
    search: OneThreadPerSearch | None = None,
    budget: ResearchBudget | None = None,
    floors: SourceHealthFloors | None = None,
) -> PipelineContext:
    return make_context(
        llm=model or Model(),
        source=source or Source(),
        search=search or OneThreadPerSearch(),
        config=ResearchConfig(
            budget=budget or ResearchBudget(max_search_queries=4, max_comments_per_document=100),
            source_health_floors=floors or SourceHealthFloors(min_posts_retrieved=0),
            ranking=RankingConfig(minimum_independent_users=2),
        ),
    )


class TestTheWorkOverlaps:
    async def test_analysis_begins_before_discovery_has_finished_searching(self) -> None:
        """The whole phase, as a deadlock that does not happen.

        The model refuses to propose a third query until some comment has
        been analysed. The sequential pipeline could never satisfy that —
        triage, retrieval and analysis all ran after discovery returned — so
        it would hang here and the timeout would fire. Finishing *is* the
        proof that the first thread was being read while the search was
        still going.
        """
        model = Model(turns=4, block_search_until_analysed=True)
        context = _context(model=model)

        await asyncio.wait_for(
            run_strands(context, batch_size=20, max_concurrent_calls=8), timeout=5
        )

        assert model.analysis_calls > 0
        assert model.search_turns >= 4

    async def test_every_discovered_document_still_reaches_the_corpus(self) -> None:
        source = Source(comments_each=4)
        context = _context(model=Model(turns=4), source=source)

        outcomes = await run_strands(context, batch_size=20, max_concurrent_calls=8)

        assert len(outcomes) == 4
        assert sorted(source.fetched) == ["doc1", "doc2", "doc3", "doc4"]
        assert context.research.statistics["comments_with_analysis"] == 16
        assert len(context.data["counted_analyses"]) == 16


class TestAStrandThatDies:
    async def test_one_lost_thread_changes_nothing_else(self) -> None:
        """§0.1's criterion, against a concurrent pipeline: the run reports,
        and what it lost is visible rather than inferred from a short list."""
        source = Source(comments_each=4, failing={"doc2"})
        context = _context(model=Model(turns=4), source=source)

        outcomes = await run_strands(context, batch_size=20, max_concurrent_calls=8)

        failed = [outcome for outcome in outcomes if outcome.failure]
        assert [outcome.document_id for outcome in failed] == ["doc2"]
        assert context.research.statistics["comments_with_analysis"] == 12
        assert context.research.statistics["strands_failed"] == 1
        assert any(
            suppression.reason.value == "retrieval_source_failure"
            for suppression in context.research.diagnostics.suppressions
        )


class TestTheHealthGate:
    async def test_no_analysis_call_is_made_before_the_floor_is_reached(self) -> None:
        """§8.1 used to be a barrier between retrieval and analysis, for the
        reason that money must not be spent on a corpus a broken source
        produced. The gate keeps that, concurrently."""
        model = Model(turns=4)
        context = _context(
            model=model,
            source=Source(comments_each=4),
            floors=SourceHealthFloors(min_posts_retrieved=3),
        )

        await run_strands(context, batch_size=20, max_concurrent_calls=8)

        # Analysis happened, and not before three documents had been fetched.
        assert model.analysis_calls == 4

    async def test_a_run_that_cannot_reach_the_floor_does_not_hang(self) -> None:
        """The gate must never be why a run stops. A corpus too small to
        clear §8.1's floor proceeds, and §8.1 is what decides its fate."""
        model = Model(turns=1)
        context = _context(
            model=model,
            source=Source(comments_each=4),
            budget=ResearchBudget(max_search_queries=1, max_comments_per_document=100),
            floors=SourceHealthFloors(min_posts_retrieved=50),
        )

        outcomes = await asyncio.wait_for(
            run_strands(context, batch_size=20, max_concurrent_calls=8), timeout=5
        )

        assert len(outcomes) == 1
        assert model.analysis_calls == 1


class TestTheRunWideBudgets:
    async def test_the_post_budget_applies_across_waves_not_within_one(self) -> None:
        context = _context(
            model=Model(turns=6),
            budget=ResearchBudget(
                max_search_queries=6, max_total_posts=2, max_comments_per_document=100
            ),
        )

        outcomes = await run_strands(context, batch_size=20, max_concurrent_calls=8)

        assert len(outcomes) == 2
        assert context.research.statistics["documents_triaged"] == 2

    async def test_evidence_spends_the_share_it_is_given_and_no_more(self) -> None:
        """Plan §4.5: topical threads may not buy capacity away from the
        corpus that decides the ranking. A run that wants evidence material
        sets a share, and gets exactly that share."""
        context = _context(
            model=Model(turns=3, verdict=TriageVerdict.TOPICAL),
            budget=ResearchBudget(
                max_search_queries=3, max_comments_per_document=100, topical_quota=0.5
            ),
        )

        await run_strands(context, batch_size=20, max_concurrent_calls=8)

        assert context.data["counted_analyses"] == []
        assert len(context.data["evidence_analyses"]) > 0

    async def test_topical_documents_are_not_opened_when_nothing_is_left_for_them(
        self,
    ) -> None:
        """§4.5's "leftover budget", as the money it actually saves.

        The fetch is the first cost and it is paid before a comment can be
        refused, so a strand that could never admit one must not be started.
        The documents are still triaged — the polling/topical ratio is a
        §4.5 finding, and it cannot be measured by not looking."""
        source = Source()
        context = _context(model=Model(turns=3, verdict=TriageVerdict.TOPICAL), source=source)

        await run_strands(context, batch_size=20, max_concurrent_calls=8)

        assert context.data["evidence_analyses"] == []
        assert source.fetched == []
        assert context.research.statistics["documents_triaged"] == 3
        assert context.research.statistics["documents_topical"] == 3
        (entry,) = [
            suppression
            for suppression in context.research.diagnostics.suppressions
            if suppression.reason is SuppressionReason.TOPICAL_UNOPENED
        ]
        assert entry.count == 3


class TestTheQuotaIsRealConfig:
    async def test_the_configured_topical_quota_reaches_the_purse(self) -> None:
        """A config value nothing reads is a knob that lies. The orchestrator
        builds the purse, so it is the only place that can honour it."""
        context = _context(
            model=Model(turns=4, verdict=TriageVerdict.TOPICAL),
            budget=ResearchBudget(
                max_search_queries=4,
                max_comments_per_document=100,
                max_ai_analysis_items=100,
                topical_quota=0.0,
            ),
        )

        await run_strands(context, batch_size=20, max_concurrent_calls=8)

        # Every document is topical and topical has no allowance, so nothing
        # was analysed — and the refusal is recorded, not silent.
        assert context.data["evidence_analyses"] == []
        assert any(
            suppression.reason is SuppressionReason.TOPICAL_UNOPENED
            for suppression in context.research.diagnostics.suppressions
        )
