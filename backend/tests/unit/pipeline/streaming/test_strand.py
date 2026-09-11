"""One document, carried end to end (plan §2.14.2, §10 Phase 14.8).

The acceptance criteria this file owns: a strand turns one document into
counted analyses without any other strand existing; the per-document cap is
what converts a bigger budget into a broader corpus rather than a deeper one;
and — the §0.1 criterion, now against a concurrent pipeline — a strand that
fails removes **only its own contribution**, records what was lost, and ends
nothing.
"""

from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel

from builders.phase7 import RecordingSourceAdapter, make_comment, make_context, make_document
from tripfinder.ai.errors import LLMUnavailableError
from tripfinder.analysis.comment_analysis import (
    CommentAnalysis,
    CommentAnalysisBatch,
    EntityMention,
)
from tripfinder.domain.config import RankingConfig, ResearchConfig
from tripfinder.domain.models import (
    Comment,
    EntityType,
    ReasonCode,
    ResearchStatus,
    Stance,
)
from tripfinder.pipeline.base import PartialResults, PipelineContext
from tripfinder.pipeline.health import get_recorder
from tripfinder.pipeline.steps.comment_analysis import CommentAnalysisStep
from tripfinder.pipeline.streaming.accumulator import Accumulator
from tripfinder.pipeline.streaming.budget import CommentClass, RunBudget
from tripfinder.pipeline.streaming.strand import StrandOutcome, run_strand

BODY = "Michigan is stunning in autumn and almost nobody ever goes there."


def _comments(count: int, *, document: str = "d1", score_from: int = 0) -> list[Comment]:
    return [
        make_comment(
            f"{document}-c{index}",
            document_id=document,
            user_id=f"{document}-u{index}",
            body=BODY,
            score=score_from + index,
        )
        for index in range(count)
    ]


class ScriptedLLM:
    """Answers every batch, or raises for the nth call."""

    def __init__(self, *, fail_on: set[int] | None = None) -> None:
        self._fail_on = fail_on or set()
        self.calls = 0
        self.in_flight = 0
        self.peak_in_flight = 0

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        self.calls += 1
        index = self.calls
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)
            if index in self._fail_on:
                raise LLMUnavailableError("provider down")
            items = [
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
                for comment_id in _ids_in(prompt)
            ]
            return CommentAnalysisBatch(items=items)  # type: ignore[return-value]
        finally:
            self.in_flight -= 1


def _ids_in(prompt: str) -> list[str]:
    """The comment ids this prompt asked about, read back out of it."""
    return re.findall(r"d\d+-c\d+", prompt)


class Listener:
    def __init__(self) -> None:
        self.received: list[PartialResults] = []

    async def __call__(self, partial: PartialResults) -> None:
        self.received.append(partial)


def _setup(
    comments_by_document: dict[str, list[Comment]],
    *,
    llm: ScriptedLLM | None = None,
    failing: dict[str, Exception] | None = None,
    max_comments: int = 1000,
    max_analysis_items: int = 1000,
    max_concurrent_calls: int = 8,
) -> tuple[PipelineContext, RunBudget, Accumulator, Listener, ScriptedLLM]:
    scripted = llm or ScriptedLLM()
    context = make_context(
        source=RecordingSourceAdapter(comments_by_document, failing=failing),
        llm=scripted,
        config=ResearchConfig(ranking=RankingConfig(minimum_independent_users=2)),
        status=ResearchStatus.ANALYZING,
    )
    listener = Listener()
    context.on_partial_results = listener
    budget = RunBudget(
        max_comments=max_comments,
        max_analysis_items=max_analysis_items,
        max_concurrent_calls=max_concurrent_calls,
        topical_quota=0.0,
    )
    return context, budget, Accumulator(context), listener, scripted


async def _run(
    context: PipelineContext,
    document_id: str,
    budget: RunBudget,
    accumulator: Accumulator,
    *,
    comment_class: CommentClass = CommentClass.COUNTED,
    comments_per_document: int = 40,
    batch_size: int = 20,
) -> StrandOutcome:
    return await run_strand(
        context,
        make_document(document_id),
        comment_class=comment_class,
        budget=budget,
        accumulator=accumulator,
        analyser=CommentAnalysisStep(batch_size=batch_size),
        recorder=get_recorder(context),
        plan=context.data["plan"],
        comments_per_document=comments_per_document,
        batch_size=batch_size,
    )


class TestOneDocumentEndToEnd:
    async def test_a_strand_turns_a_document_into_counted_analyses(self) -> None:
        context, budget, accumulator, listener, _ = _setup({"d1": _comments(5)})

        outcome = await _run(context, "d1", budget, accumulator)

        assert outcome.failure is None
        assert outcome.comments_fetched == 5
        assert outcome.comments_analysed == 5
        counted, evidence = accumulator.corpus()
        assert len(counted) == 5
        assert evidence == []

    async def test_a_strand_never_ranks_only_the_accumulator_does(self) -> None:
        """One person, one vote holds across documents, which no strand can
        see (plan §2.14.2). The strand's job ends at the accumulator."""
        context, budget, accumulator, listener, _ = _setup({"d1": _comments(3)})

        await _run(context, "d1", budget, accumulator)

        assert listener.received, "the accumulator produced no ranking"
        assert {
            result.entity_name for result in listener.received[-1].weak_results
        } | {result.entity_name for result in listener.received[-1].results} == {"Michigan"}

    async def test_evidence_material_stays_out_of_the_counted_corpus(self) -> None:
        """Plan §4.5: a topical thread's users may not enter the pool."""
        context, budget, accumulator, _, _ = _setup({"d1": _comments(3)}, max_comments=100)
        budget = RunBudget(
            max_comments=100, max_analysis_items=100, max_concurrent_calls=8, topical_quota=1.0
        )

        await _run(context, "d1", budget, accumulator, comment_class=CommentClass.EVIDENCE)

        counted, evidence = accumulator.corpus()
        assert counted == []
        assert len(evidence) == 3


class TestThePerDocumentCap:
    async def test_a_thread_gives_up_only_its_share(self) -> None:
        """§2.12.3's finding 1 as a rule: without a cap, twelve threads
        supplied a whole run's evidence and sixty-six were never opened."""
        context, budget, accumulator, _, _ = _setup({"d1": _comments(100)})

        outcome = await _run(context, "d1", budget, accumulator, comments_per_document=40)

        assert outcome.comments_fetched == 100
        assert outcome.comments_admitted == 40

    async def test_the_cap_keeps_the_best_scoring_comments(self) -> None:
        context, budget, accumulator, _, _ = _setup({"d1": _comments(10)})

        await _run(context, "d1", budget, accumulator, comments_per_document=3)

        counted, _ = accumulator.corpus()
        assert {analysis.comment_id for analysis in counted} == {"d1-c9", "d1-c8", "d1-c7"}

    async def test_what_the_cap_dropped_is_recorded_not_silently_lost(self) -> None:
        context, budget, accumulator, _, _ = _setup({"d1": _comments(100)})

        await _run(context, "d1", budget, accumulator, comments_per_document=40)

        dropped = [
            suppression
            for suppression in context.research.diagnostics.suppressions
            if suppression.step == "strand"
        ]
        assert sum(suppression.count for suppression in dropped) == 60


class TestTheSharedPurse:
    async def test_a_strand_takes_only_what_it_is_granted(self) -> None:
        context, budget, accumulator, _, _ = _setup({"d1": _comments(50)}, max_comments=10)

        outcome = await _run(context, "d1", budget, accumulator, comments_per_document=50)

        assert outcome.comments_admitted == 10

    async def test_a_strand_that_is_granted_nothing_costs_no_model_call(self) -> None:
        context, budget, accumulator, _, llm = _setup({"d1": _comments(50)}, max_comments=0)

        outcome = await _run(context, "d1", budget, accumulator)

        assert outcome.comments_admitted == 0
        assert llm.calls == 0

    async def test_concurrency_is_bounded_on_calls_not_on_strands(self) -> None:
        """Plan §2.14.2: strands are cheap, model calls are not."""
        llm = ScriptedLLM()
        context, budget, accumulator, _, _ = _setup(
            {f"d{index}": _comments(20, document=f"d{index}") for index in range(10)},
            llm=llm,
            max_concurrent_calls=3,
        )

        await asyncio.gather(
            *(_run(context, f"d{index}", budget, accumulator) for index in range(10))
        )

        assert llm.calls == 10
        assert llm.peak_in_flight <= 3

    async def test_nothing_is_started_once_the_analysis_budget_is_gone(self) -> None:
        context, budget, accumulator, _, llm = _setup(
            {"d1": _comments(100)}, max_analysis_items=20
        )

        outcome = await _run(context, "d1", budget, accumulator, comments_per_document=100)

        assert llm.calls == 1
        assert outcome.comments_analysed == 20


class TestAStrandThatFails:
    async def test_a_lost_source_removes_only_this_document(self) -> None:
        """The §0.1 criterion against a concurrent pipeline: the run still
        reports, and the loss is visible rather than inferred."""
        context, budget, accumulator, _, _ = _setup(
            {"d2": _comments(4, document="d2")},
            failing={"d1": ConnectionError("thread gone")},
        )

        first, second = await asyncio.gather(
            _run(context, "d1", budget, accumulator),
            _run(context, "d2", budget, accumulator),
        )

        assert first.failure == "source_fetch_failed"
        assert second.failure is None and second.comments_analysed == 4
        assert any(
            suppression.reason.value == "retrieval_source_failure"
            for suppression in context.research.diagnostics.suppressions
        )

    async def test_a_lost_analysis_batch_removes_only_that_batch(self) -> None:
        llm = ScriptedLLM(fail_on={1})
        context, budget, accumulator, _, _ = _setup({"d1": _comments(40)}, llm=llm)

        outcome = await _run(context, "d1", budget, accumulator, comments_per_document=40)

        assert outcome.batches_attempted == 2
        assert outcome.batches_failed == 1
        assert outcome.comments_analysed == 20
        assert any(
            suppression.reason.value == "analysis_batch_failed"
            for suppression in context.research.diagnostics.suppressions
        )

    async def test_a_strand_never_raises_whatever_goes_wrong(self) -> None:
        """Eighty of these run at once. One raising would end the run."""
        context, budget, accumulator, _, _ = _setup({"d1": _comments(4)})
        context.data.pop("plan")

        outcome = await run_strand(
            context,
            make_document("d1"),
            comment_class=CommentClass.COUNTED,
            budget=budget,
            accumulator=accumulator,
            analyser=CommentAnalysisStep(batch_size=20),
            recorder=get_recorder(context),
            plan=None,  # type: ignore[arg-type]
            comments_per_document=40,
            batch_size=20,
        )

        assert outcome.failure is not None
        assert outcome.comments_analysed == 0


class TestAnEmptyDocument:
    async def test_a_document_with_no_substantive_comments_costs_no_call(self) -> None:
        context, budget, accumulator, _, llm = _setup(
            {"d1": [make_comment("d1-c0", document_id="d1", user_id="u0", body="yes")]}
        )

        outcome = await _run(context, "d1", budget, accumulator)

        assert outcome.comments_fetched == 1
        assert outcome.comments_admitted == 0
        assert llm.calls == 0
