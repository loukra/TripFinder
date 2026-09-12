"""Provisional snapshots (plan §2.13, §10 Phase 14.7).

The acceptance criteria this file owns, in plan order: a snapshot and a full
aggregation agree over an identical closed corpus; a snapshot issues zero
model calls; nothing about the run is derived from one — least of all its
terminal status; and a snapshot under-reports rather than over-reports when
a name is beyond the catalogue.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import BaseModel

from builders.phase7 import make_comment, make_context
from tripfinder.analysis.comment_analysis import CommentAnalysis, EntityMention
from tripfinder.analysis.entity_resolution import EntityResolutionBatch, ResolvedName
from tripfinder.domain.config import RankingConfig, ResearchConfig
from tripfinder.domain.models import (
    Comment,
    EntityType,
    ReasonCode,
    ResearchStatus,
    Result,
    Stance,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.snapshot import snapshot
from tripfinder.pipeline.steps.aggregation import AggregationStep
from tripfinder.pipeline.steps.entity_resolution import EntityResolutionStep
from tripfinder.pipeline.steps.user_deduplication import UserDeduplicationStep


class CountingLLM:
    """Answers nothing, and counts every attempt to ask it something.

    Anything a snapshot sends here is a cost the run did not budget for —
    a snapshot happens after every analysis batch (plan §2.13).
    """

    def __init__(self, answers: Sequence[EntityResolutionBatch] = ()) -> None:
        self._answers = list(answers)
        self.calls = 0

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        self.calls += 1
        answer = self._answers[self.calls - 1]
        assert isinstance(answer, response_model)
        return answer


def _mention(raw_text: str, quote: str = "a verbatim span") -> EntityMention:
    return EntityMention(
        raw_text=raw_text,
        entity_type=EntityType.STATE,
        stance=Stance.POSITIVE,
        strength=0.8,
        supporting_quote=quote,
    )


def _analysis(comment_id: str, *mentions: EntityMention) -> CommentAnalysis:
    return CommentAnalysis(
        comment_id=comment_id,
        topic_relevance=0.9,
        criterion_relevance=0.9,
        scope_match=True,
        overall_confidence=0.9,
        mentions=list(mentions),
        reason_code=ReasonCode.RECOMMENDS,
    )


# Three people for Alaska, two for Vermont, one for Maine — every name in the
# catalogue, so the deterministic half settles all of them and the two paths
# have the same corpus to work from.
CORPUS: tuple[tuple[str, str, str], ...] = (
    ("c1", "u1", "Alaska"),
    ("c2", "u2", "Alaska"),
    ("c3", "u3", "Alaska"),
    ("c4", "u4", "Vermont"),
    ("c5", "u5", "Vermont"),
    ("c6", "u6", "Maine"),
)


def _comments(corpus: Sequence[tuple[str, str, str]] = CORPUS) -> list[Comment]:
    return [make_comment(cid, user_id=uid) for cid, uid, _ in corpus]


def _analyses(corpus: Sequence[tuple[str, str, str]] = CORPUS) -> list[CommentAnalysis]:
    return [_analysis(cid, _mention(name)) for cid, _, name in corpus]


def _context(
    *,
    corpus: Sequence[tuple[str, str, str]] = CORPUS,
    llm: CountingLLM | None = None,
) -> PipelineContext:
    """A context at the point analysis has produced ``corpus``'s analyses."""
    context = make_context(
        llm=llm or CountingLLM(),
        config=ResearchConfig(ranking=RankingConfig(minimum_independent_users=2)),
        status=ResearchStatus.ANALYZING,
    )
    context.data["comments"] = _comments(corpus)
    return context


async def _full_pass(
    context: PipelineContext,
    *,
    counted: Sequence[CommentAnalysis],
    evidence: Sequence[CommentAnalysis] = (),
) -> tuple[list[Result], list[Result]]:
    """Steps 8-11 as the run itself runs them, on the given context."""
    context.data["counted_analyses"] = list(counted)
    context.data["evidence_analyses"] = list(evidence)
    context.data["comment_analyses"] = [*counted, *evidence]
    for step in (EntityResolutionStep(), UserDeduplicationStep(), AggregationStep()):
        context = await step.run(context)
    return context.research.results, context.research.weak_results


class TestItIsTheSameMetric:
    """Plan §2.13: a snapshot is the run's own steps 8-11, not a second
    implementation of the metric. These tests exist to keep it that way."""

    async def test_a_snapshot_matches_a_full_aggregation_over_the_same_corpus(self) -> None:
        analyses = _analyses()

        provisional = await snapshot(
            _context(), counted_analyses=analyses, evidence_analyses=[]
        )
        final = await _full_pass(_context(), counted=analyses)

        assert provisional == final

    async def test_it_counts_the_supporters_a_partial_corpus_holds(self) -> None:
        """Not a tautology against the test above: it pins the numbers, so a
        snapshot that seeded only some of the three context keys entity
        resolution and deduplication read (plan §2.13) would show up as a
        silently smaller count rather than as an identical pair of zeros."""
        strong, weak = await snapshot(
            _context(), counted_analyses=_analyses(CORPUS[:4]), evidence_analyses=[]
        )

        assert [(result.entity_name, result.supporter_count) for result in [*strong, *weak]] == [
            ("Alaska", 3),
            ("Vermont", 1),
        ]

    async def test_counts_only_grow_as_more_comments_are_analysed(self) -> None:
        """Plan §2.13.1's promise, and the reason counts may be shown early."""
        seen: list[int] = []
        for size in range(1, len(CORPUS) + 1):
            strong, weak = await snapshot(
                _context(), counted_analyses=_analyses(CORPUS[:size]), evidence_analyses=[]
            )
            alaska = next(
                (r for r in [*strong, *weak] if r.entity_name == "Alaska"), None
            )
            seen.append(0 if alaska is None else alaska.supporter_count)

        assert seen == sorted(seen)
        assert seen[-1] == 3


class TestItNeverAsksTheModel:
    async def test_a_snapshot_issues_no_llm_calls(self) -> None:
        llm = CountingLLM()

        await snapshot(
            _context(llm=llm), counted_analyses=_analyses(), evidence_analyses=[]
        )

        assert llm.calls == 0

    async def test_a_name_the_catalogue_cannot_place_is_left_uncounted(self) -> None:
        """The safe direction: a snapshot under-reports rather than guesses.

        The full pass asks the model and merges *Zorgland* into Alaska; the
        snapshot cannot, so its Alaska count is a floor on the final one —
        which is exactly what plan §2.13.1 promises a provisional number is.
        """
        corpus = (*CORPUS, ("c7", "u7", "Zorgland"))
        analyses = _analyses(corpus)
        llm = CountingLLM(
            [
                EntityResolutionBatch(
                    items=[
                        ResolvedName(
                            surface_form="Zorgland",
                            canonical_name="Alaska",
                            confidence=0.95,
                            reason="a nickname for Alaska",
                        )
                    ]
                )
            ]
        )

        strong, _ = await snapshot(
            _context(corpus=corpus, llm=llm), counted_analyses=analyses, evidence_analyses=[]
        )
        final_strong, _ = await _full_pass(
            _context(corpus=corpus, llm=llm), counted=analyses
        )

        assert llm.calls == 1  # the full pass's, not the snapshot's
        assert strong[0].entity_name == "Alaska"
        assert strong[0].supporter_count == 3
        assert final_strong[0].supporter_count == 4


class TestNothingIsDerivedFromASnapshot:
    """Plan §2.13.2: a snapshot is display state. The run's record is the
    output of the full pass, and a snapshot must not be able to touch it."""

    @pytest.fixture
    def context(self) -> PipelineContext:
        return _context()

    async def test_it_does_not_settle_the_runs_terminal_status(
        self, context: PipelineContext
    ) -> None:
        """The trap this whole design is arranged around: aggregation ends by
        setting the terminal status, so a snapshot that copied anything back
        would have a run announce itself finished sixty seconds in."""
        await snapshot(context, counted_analyses=_analyses(), evidence_analyses=[])

        assert context.research.status is ResearchStatus.ANALYZING

    async def test_it_leaves_the_runs_results_alone(self, context: PipelineContext) -> None:
        await snapshot(context, counted_analyses=_analyses(), evidence_analyses=[])

        assert context.research.results == []
        assert context.research.weak_results == []

    async def test_it_writes_no_statistics_and_no_suppressions(
        self, context: PipelineContext
    ) -> None:
        await snapshot(context, counted_analyses=_analyses(), evidence_analyses=[])

        assert context.research.statistics == {}
        assert context.research.diagnostics.suppressions == []
        assert context.research.diagnostics.entity_resolutions == []

    async def test_it_leaves_no_keys_behind_in_the_context(
        self, context: PipelineContext
    ) -> None:
        """The steps write ``entities``, ``counted_opinions`` and more. On the
        run's own context those are the *final* pass's to write."""
        before = set(context.data)

        await snapshot(context, counted_analyses=_analyses(), evidence_analyses=[])

        assert set(context.data) == before

    async def test_snapshotting_twice_changes_nothing(
        self, context: PipelineContext
    ) -> None:
        analyses = _analyses()

        first = await snapshot(context, counted_analyses=analyses, evidence_analyses=[])
        second = await snapshot(context, counted_analyses=analyses, evidence_analyses=[])

        assert first == second

    async def test_a_full_pass_after_a_snapshot_is_unaffected_by_it(
        self, context: PipelineContext
    ) -> None:
        """The order a real run does it in: snapshot, snapshot, then rank."""
        analyses = _analyses()
        await snapshot(context, counted_analyses=_analyses(CORPUS[:2]), evidence_analyses=[])
        await snapshot(context, counted_analyses=_analyses(CORPUS[:4]), evidence_analyses=[])

        final = await _full_pass(context, counted=analyses)

        assert final == await _full_pass(_context(), counted=analyses)
        # The run's own verdict, reached despite two snapshots having run the
        # same steps against a copy first. `_full_pass` stops at aggregation,
        # which is where the verdict is decided; Summarization publishes it.
        assert context.data["terminal_status"] is ResearchStatus.COMPLETED
        assert context.research.status is not ResearchStatus.COMPLETED


class TestTheCorpusSplitSurvives:
    async def test_an_evidence_only_comment_never_reaches_the_respondent_pool(self) -> None:
        """Plan §4.5, still true of a provisional ranking: a topical thread's
        users illustrate the answer, they do not vote in it."""
        counted = _analyses(CORPUS[:2])
        evidence = [_analysis("c9", _mention("Maine"))]
        context = _context()
        context.data["comments"] = [*_comments(CORPUS[:2]), make_comment("c9", user_id="u9")]

        strong, weak = await snapshot(
            context, counted_analyses=counted, evidence_analyses=evidence
        )

        ranked = [*strong, *weak]
        assert [result.entity_name for result in ranked] == ["Alaska"]
        assert ranked[0].respondent_pool_size == 2
