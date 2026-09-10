from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from tripfinder.ai.errors import (
    LLMCredentialError,
    LLMProviderError,
    LLMResponseError,
    LLMUnavailableError,
)
from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.domain.models import FailureKind, Research, ResearchStatus, Result
from tripfinder.pipeline.base import PipelineContext, PipelineStep, ProgressEvent
from tripfinder.pipeline.runner import PipelineRunner
from tripfinder.sources.fake.adapter import FakeSourceAdapter


class _SetsStatusStep:
    def __init__(self, name: str, status: ResearchStatus) -> None:
        self.name = name
        self._status = status

    async def run(self, context: PipelineContext) -> PipelineContext:
        context.research.status = self._status
        return context


class _FailingStep:
    name = "failing"

    async def run(self, context: PipelineContext) -> PipelineContext:
        raise RuntimeError("boom")


def _context() -> PipelineContext:
    research = Research(
        original_query="most underrated states",
        created_at=datetime.now(UTC),
        status=ResearchStatus.PENDING,
    )
    return PipelineContext(research=research, source=FakeSourceAdapter(), llm=FakeLLMProvider())


def test_step_satisfies_pipeline_step_protocol() -> None:
    assert isinstance(_SetsStatusStep("s", ResearchStatus.DISCOVERING), PipelineStep)


async def test_runs_steps_in_order_and_threads_context_through() -> None:
    steps = [
        _SetsStatusStep("first", ResearchStatus.DISCOVERING),
        _SetsStatusStep("second", ResearchStatus.RETRIEVING),
    ]
    runner = PipelineRunner(steps)

    result = await runner.run(_context())

    assert result.research.status == ResearchStatus.RETRIEVING


async def test_records_a_progress_event_per_step_in_sequence() -> None:
    steps = [
        _SetsStatusStep("first", ResearchStatus.DISCOVERING),
        _SetsStatusStep("second", ResearchStatus.RETRIEVING),
    ]
    runner = PipelineRunner(steps)

    result = await runner.run(_context())

    assert result.progress == [
        ProgressEvent(sequence=1, step_name="first", status=ResearchStatus.DISCOVERING),
        ProgressEvent(sequence=2, step_name="second", status=ResearchStatus.RETRIEVING),
    ]


async def test_invokes_on_progress_callback_for_each_step() -> None:
    seen: list[ProgressEvent] = []
    runner = PipelineRunner(
        [_SetsStatusStep("only", ResearchStatus.DISCOVERING)],
        on_progress=seen.append,
    )

    await runner.run(_context())

    assert seen == [ProgressEvent(sequence=1, step_name="only", status=ResearchStatus.DISCOVERING)]


async def test_a_failing_step_propagates_and_records_no_progress_for_it() -> None:
    runner = PipelineRunner(
        [_SetsStatusStep("first", ResearchStatus.DISCOVERING), _FailingStep()]
    )
    context = _context()

    try:
        await runner.run(context)
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass

    assert [event.step_name for event in context.progress] == ["first"]


class _RecordingStep:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ran = False

    async def run(self, context: PipelineContext) -> PipelineContext:
        self.ran = True
        return context


@pytest.mark.parametrize(
    "status",
    [
        ResearchStatus.SOURCE_UNAVAILABLE,
        ResearchStatus.REJECTED,
        ResearchStatus.NEEDS_CLARIFICATION,
        ResearchStatus.FAILED,
        ResearchStatus.CANCELLED,
    ],
)
async def test_a_halting_status_stops_the_remaining_steps(status: ResearchStatus) -> None:
    """Plan §7: a terminated research must not go on to build output it may not have."""
    later = _RecordingStep("later")
    runner = PipelineRunner([_SetsStatusStep("halts", status), later])

    context = await runner.run(_context())

    assert later.ran is False
    assert [event.step_name for event in context.progress] == ["halts"]
    assert context.research.status is status


async def test_a_non_halting_status_lets_the_pipeline_continue() -> None:
    later = _RecordingStep("later")
    runner = PipelineRunner([_SetsStatusStep("first", ResearchStatus.RETRIEVING), later])

    await runner.run(_context())

    assert later.ran is True


class _RaisingProviderStep:
    """A step whose LLM call fails, the way every AI step's can."""

    name = "asks_the_model"

    def __init__(self, error: LLMProviderError) -> None:
        self._error = error

    async def run(self, context: PipelineContext) -> PipelineContext:
        raise self._error


class TestAnLLMProviderFailureEndsTheRun:
    """Plan §0.1: an unreachable model is no more a finding than an unreachable source.

    Caught in the runner rather than in each AI step, because every AI step
    raises the same failures and every one must end the run the same way.
    """

    async def test_the_research_fails_rather_than_propagating(self) -> None:
        runner = PipelineRunner([_RaisingProviderStep(LLMCredentialError("no key"))])

        context = await runner.run(_context())

        assert context.research.status is ResearchStatus.FAILED

    async def test_the_cause_is_named_with_its_kind_and_step(self) -> None:
        runner = PipelineRunner([_RaisingProviderStep(LLMUnavailableError("timed out"))])

        context = await runner.run(_context())

        failure = context.research.diagnostics.failure
        assert failure is not None
        assert failure.kind is FailureKind.LLM_UNAVAILABLE
        assert failure.step == "asks_the_model"
        assert "timed out" in failure.detail

    async def test_any_results_built_so_far_are_discarded(self) -> None:
        """§7.1: a failed run has no results page, so it may not carry results."""
        context = _context()
        context.research.results = [
            Result(
                entity_id="alaska",
                entity_name="Alaska",
                supporter_count=3,
                share=0.25,
                respondent_pool_size=12,
                discussion_count=2,
                weighted_score=3.0,
                confidence=0.9,
            )
        ]
        runner = PipelineRunner([_RaisingProviderStep(LLMCredentialError("no key"))])

        context = await runner.run(context)

        assert context.research.results == []

    async def test_later_steps_do_not_run(self) -> None:
        later = _RecordingStep("later")
        runner = PipelineRunner(
            [_RaisingProviderStep(LLMResponseError("refused")), later]
        )

        await runner.run(_context())

        assert later.ran is False

    async def test_the_failing_step_records_a_progress_event(self) -> None:
        runner = PipelineRunner([_RaisingProviderStep(LLMCredentialError("no key"))])

        context = await runner.run(_context())

        assert context.progress == [
            ProgressEvent(
                sequence=1, step_name="asks_the_model", status=ResearchStatus.FAILED
            )
        ]

    async def test_the_first_cause_is_the_one_kept(self) -> None:
        """The original failure is what explains the missing evidence."""
        context = _context()
        context.research.diagnostics.record_failure(
            kind=FailureKind.LLM_UNAVAILABLE, step="earlier", detail="the first one"
        )
        runner = PipelineRunner([_RaisingProviderStep(LLMCredentialError("no key"))])

        context = await runner.run(context)

        failure = context.research.diagnostics.failure
        assert failure is not None
        assert failure.step == "earlier"

    async def test_a_non_provider_error_still_propagates(self) -> None:
        """Only LLM failures are converted. Everything else is Phase 13's error contract."""
        runner = PipelineRunner([_FailingStep()])

        with pytest.raises(RuntimeError):
            await runner.run(_context())


class TestCancellationBetweenSteps:
    """Plan §10 Phase 13. Checked between steps only — see ``CancellationCheck``'s docstring
    in ``runner.py`` for why a step already in flight always finishes first."""

    async def test_a_true_should_cancel_stops_the_run_and_marks_it_cancelled(self) -> None:
        later = _RecordingStep("later")
        runner = PipelineRunner(
            [_SetsStatusStep("first", ResearchStatus.DISCOVERING), later]
        )

        context = await runner.run(_context(), should_cancel=_always(True))

        assert later.ran is False
        assert context.research.status is ResearchStatus.CANCELLED
        assert [event.step_name for event in context.progress] == ["first"]

    async def test_a_false_should_cancel_lets_the_pipeline_continue(self) -> None:
        later = _RecordingStep("later")
        runner = PipelineRunner(
            [_SetsStatusStep("first", ResearchStatus.DISCOVERING), later]
        )

        await runner.run(_context(), should_cancel=_always(False))

        assert later.ran is True

    async def test_should_cancel_is_never_consulted_once_the_run_already_halted(self) -> None:
        """A step that already ended the run (rejected, failed...) takes priority —
        cancellation must not overwrite a status that already explains itself."""
        calls = 0

        async def _should_cancel() -> bool:
            nonlocal calls
            calls += 1
            return True

        runner = PipelineRunner([_SetsStatusStep("rejects", ResearchStatus.REJECTED)])

        context = await runner.run(_context(), should_cancel=_should_cancel)

        assert context.research.status is ResearchStatus.REJECTED
        assert calls == 0

    async def test_no_should_cancel_behaves_exactly_as_before(self) -> None:
        runner = PipelineRunner([_SetsStatusStep("first", ResearchStatus.DISCOVERING)])

        context = await runner.run(_context())

        assert context.research.status is ResearchStatus.DISCOVERING


def _always(value: bool) -> Callable[[], Any]:
    async def _check() -> bool:
        return value

    return _check
