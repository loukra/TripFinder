from datetime import UTC, datetime

import pytest

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.domain.models import Research, ResearchStatus
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
