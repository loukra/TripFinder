"""Snapshots emitted while comment analysis runs (plan §2.13, §10 Phase 14.7).

``test_comment_analysis.py`` owns what the step produces; this file owns
*when* it says something. The acceptance criteria here: a ranked,
non-empty provisional result reaches a listener **before** the step
completes; every snapshot is cumulative, so the counts a client reads never
go backwards; snapshots coalesce rather than queueing one per batch; and a
run with nowhere to send them behaves exactly as it did before.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from pydantic import BaseModel, HttpUrl

from builders.phase7 import make_context
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
from tripfinder.pipeline.steps.comment_analysis import CommentAnalysisStep

# One comment per person, each recommending a state the catalogue holds, so
# the deterministic half of entity resolution settles every name and a
# snapshot never needs the model (plan §2.13).
SUPPORTERS: tuple[tuple[str, str, str], ...] = (
    ("c1", "u1", "Alaska"),
    ("c2", "u2", "Alaska"),
    ("c3", "u3", "Alaska"),
    ("c4", "u4", "Vermont"),
    ("c5", "u5", "Vermont"),
    ("c6", "u6", "Maine"),
    ("c7", "u7", "Alaska"),
    ("c8", "u8", "Vermont"),
)


def _body(name: str) -> str:
    return f"{name} is stunning in autumn and almost nobody goes there."


def _comment(comment_id: str, user_id: str, name: str) -> Comment:
    return Comment(
        id=comment_id,
        source_document_id="d1",
        user_id=user_id,
        body=_body(name),
        created_at="2026-06-01T00:00:00Z",  # type: ignore[arg-type]
        permalink=HttpUrl(f"https://reddit.com/comments/{comment_id}"),
    )


def _answer(comment_id: str, name: str) -> CommentAnalysisBatch:
    return CommentAnalysisBatch(
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
                        raw_text=name,
                        entity_type=EntityType.STATE,
                        stance=Stance.POSITIVE,
                        strength=0.8,
                        supporting_quote=_body(name),
                    )
                ],
            )
        ]
    )


class ScriptedLLM:
    """One batch per call, answered in dispatch order.

    ``dispatched`` and ``answered`` are counted separately because batches
    run concurrently (14.6b): every batch is sent before any of them comes
    back, and what a snapshot can possibly know about is what has come back.
    """

    def __init__(self, answers: Sequence[CommentAnalysisBatch | Exception]) -> None:
        self._answers = list(answers)
        self.dispatched = 0
        self.answered = 0

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        answer = self._answers[self.dispatched]
        self.dispatched += 1
        await asyncio.sleep(0)
        self.answered += 1
        if isinstance(answer, Exception):
            raise answer
        assert isinstance(answer, response_model)
        return answer


class Listener:
    """Collects snapshots, and records how much of the run had happened."""

    def __init__(self, llm: ScriptedLLM) -> None:
        self._llm = llm
        self.received: list[PartialResults] = []
        self.batches_answered_at_emission: list[int] = []

    async def __call__(self, partial: PartialResults) -> None:
        self.received.append(partial)
        self.batches_answered_at_emission.append(self._llm.answered)


def _context(
    corpus: Sequence[tuple[str, str, str]] = SUPPORTERS,
    *,
    answers: Sequence[CommentAnalysisBatch | Exception] | None = None,
) -> tuple[PipelineContext, ScriptedLLM]:
    scripted = [_answer(cid, name) for cid, _, name in corpus] if answers is None else list(answers)
    llm = ScriptedLLM(scripted)
    context = make_context(
        llm=llm,
        config=ResearchConfig(ranking=RankingConfig(minimum_independent_users=2)),
        status=ResearchStatus.ANALYZING,
    )
    comments = [_comment(cid, uid, name) for cid, uid, name in corpus]
    context.data["counted_comments"] = comments
    context.data["evidence_comments"] = []
    context.data["comments"] = comments
    return context, llm


def _step() -> CommentAnalysisStep:
    # One comment per batch, so "after every batch" is observable at all.
    return CommentAnalysisStep(batch_size=1)


def _counts(partial: PartialResults) -> dict[str, int]:
    return {
        result.entity_name: result.supporter_count
        for result in [*partial.results, *partial.weak_results]
    }


class TestAProvisionalResultArrivesBeforeTheStepFinishes:
    async def test_a_listener_is_given_a_ranked_result_mid_analysis(self) -> None:
        context, llm = _context()
        listener = Listener(llm)
        context.on_partial_results = listener

        await _step().run(context)

        assert listener.received, "analysis produced no provisional result at all"
        first = listener.received[0]
        assert first.results or first.weak_results
        # The point of the phase: the first ranking existed while there were
        # still batches to answer, not once every one of them was in.
        assert listener.batches_answered_at_emission[0] < len(SUPPORTERS)

    async def test_every_snapshot_is_cumulative_and_counts_never_go_down(self) -> None:
        """Plan §2.13.1 — the one promise that makes an unfinished ranking
        safe to show. A snapshot covering only the batch that has just come
        back would fail this on the second emission."""
        context, llm = _context()
        listener = Listener(llm)
        context.on_partial_results = listener

        await _step().run(context)

        seen: dict[str, int] = {}
        for partial in listener.received:
            for name, count in _counts(partial).items():
                assert count >= seen.get(name, 0)
                seen[name] = count
        assert seen == {"Alaska": 4, "Vermont": 3, "Maine": 1}

    async def test_the_sequence_number_only_advances(self) -> None:
        context, llm = _context()
        listener = Listener(llm)
        context.on_partial_results = listener

        await _step().run(context)

        sequences = [partial.batches_completed for partial in listener.received]
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences)
        assert sequences[-1] == len(SUPPORTERS)
        assert listener.received[-1].comments_analysed == len(SUPPORTERS)

    async def test_snapshots_cost_no_model_calls(self) -> None:
        """One call per batch and not one more — a snapshot after every batch
        that asked the model anything would double a run's bill."""
        context, llm = _context()
        context.on_partial_results = Listener(llm)

        await _step().run(context)

        assert llm.dispatched == len(SUPPORTERS)


class TestCoalescing:
    async def test_batches_that_land_during_a_computation_produce_one_snapshot(self) -> None:
        """Plan §2.13.2: eight batches finishing at once must not mean eight
        computations and eight writes racing each other.

        The listener holds the first snapshot until every batch has come
        back, so all the rest are known to have finished while a computation
        was in flight. They coalesce into exactly one more.
        """
        context, llm = _context()
        gate = asyncio.Event()
        received: list[PartialResults] = []

        async def listener(partial: PartialResults) -> None:
            received.append(partial)
            if len(received) == 1:
                # Held until the last batch is in — see below.
                await gate.wait()

        async def watch() -> None:
            while llm.answered < len(SUPPORTERS):
                await asyncio.sleep(0)
            gate.set()

        context.on_partial_results = listener
        await asyncio.gather(_step().run(context), watch())

        assert len(received) == 2
        assert received[0].batches_completed == 1
        assert received[1].batches_completed == len(SUPPORTERS)
        assert _counts(received[1]) == {"Alaska": 4, "Vermont": 3, "Maine": 1}


class TestARunWithNowhereToSendThem:
    async def test_no_listener_means_no_snapshots_and_no_change(self) -> None:
        """Every earlier phase's call site leaves ``on_partial_results`` unset."""
        with_listener, first_llm = _context()
        with_listener.on_partial_results = Listener(first_llm)
        without, second_llm = _context()

        await _step().run(with_listener)
        await _step().run(without)

        assert without.on_partial_results is None
        assert second_llm.dispatched == first_llm.dispatched
        assert without.research.statistics == with_listener.research.statistics
        assert without.data["counted_analyses"] == with_listener.data["counted_analyses"]


class TestAFailedBatch:
    async def test_a_batch_that_failed_contributes_nothing_and_stops_nothing(self) -> None:
        """§8.1's isolation (14.6c) and §2.13's snapshots have to coexist: a
        failed batch adds no analyses, so it emits no snapshot, and the
        batches around it still report theirs."""
        corpus = SUPPORTERS[:4]
        answers: list[CommentAnalysisBatch | Exception] = [
            _answer(corpus[0][0], corpus[0][2]),
            LLMUnavailableError("provider down"),
            _answer(corpus[2][0], corpus[2][2]),
            _answer(corpus[3][0], corpus[3][2]),
        ]
        context, llm = _context(corpus, answers=answers)
        listener = Listener(llm)
        context.on_partial_results = listener

        await _step().run(context)

        assert len(listener.received) <= 3
        assert listener.received[-1].comments_analysed == 3
        assert _counts(listener.received[-1]) == {"Alaska": 2, "Vermont": 1}
        assert context.research.statistics["comments_lost_to_errors"] == 1
