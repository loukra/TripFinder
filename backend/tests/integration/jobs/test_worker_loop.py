"""Worker loop integration tests (plan §10 Phase 3).

Runs the real queue mechanics against a real Postgres with the fake pipeline
(Phase 2) doing the "work" — the worker doesn't know or care that the
pipeline is fake.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import FailureKind, Research, ResearchStatus, Result
from tripfinder.jobs.repository import JobRepository
from tripfinder.jobs.worker_loop import run_once, run_worker_loop
from tripfinder.persistence.repositories import ResearchRepository
from tripfinder.pipeline.base import PartialResults, PipelineContext
from tripfinder.pipeline.real_pipeline import build_pipeline_context_for
from tripfinder.pipeline.runner import PipelineRunner, ProgressListener
from tripfinder.settings import Settings


async def test_run_once_processes_a_claimed_job_end_to_end(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)

    processed = await run_once(session_factory)
    assert processed is True

    async with session_factory() as session:
        fetched = await ResearchRepository(session).get(research.id)
        job_status = await JobRepository(session).get_status(job_id)

    assert fetched is not None
    assert fetched.status == ResearchStatus.COMPLETED
    assert fetched.results
    assert job_status == "succeeded"


async def test_run_once_returns_false_when_the_queue_is_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await run_once(session_factory) is False


async def test_a_cancellation_flagged_before_the_run_stops_it_between_steps(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """Plan §10 Phase 13: the API can flag a job before the worker even claims it —
    the worker still stops between steps rather than running the fake pipeline through."""
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)
    async with session_factory() as session:
        await JobRepository(session).request_cancel(job_id)

    processed = await run_once(session_factory)
    assert processed is True

    async with session_factory() as session:
        job_status = await JobRepository(session).get_status(job_id)
        fetched = await ResearchRepository(session).get(research.id)

    assert job_status == "cancelled"
    assert fetched is not None
    assert fetched.status == ResearchStatus.CANCELLED


async def test_two_identical_searches_produce_two_distinct_completed_records(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """Plan §10 Phase 3 acceptance, exercised end-to-end through the worker."""
    first = make_research()
    second = make_research()

    async with session_factory() as session:
        repo = ResearchRepository(session)
        await repo.create(first)
        await repo.create(second)
        jobs = JobRepository(session)
        await jobs.enqueue(first.id)
        await jobs.enqueue(second.id)

    await run_worker_loop(session_factory, max_iterations=2, poll_interval_seconds=0)

    async with session_factory() as session:
        repo = ResearchRepository(session)
        fetched_first = await repo.get(first.id)
        fetched_second = await repo.get(second.id)

    assert fetched_first is not None
    assert fetched_second is not None
    assert fetched_first.id != fetched_second.id
    assert fetched_first.status == ResearchStatus.COMPLETED
    assert fetched_second.status == ResearchStatus.COMPLETED


async def test_research_status_is_persisted_after_each_step_not_only_at_the_end(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without this, a real run only writes its status once, at the very
    end — the API has nothing to report but "pending" for a run's entire
    duration, even minutes into one that is actively working (plan §7.1)."""
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    async with session_factory() as session:
        await JobRepository(session).enqueue(research.id)

    seen_mid_run: list[ResearchStatus] = []

    class _SetsStatusStep:
        name = "discovers"

        async def run(self, context: PipelineContext) -> PipelineContext:
            context.research.status = ResearchStatus.DISCOVERING
            return context

    class _ProbeStep:
        name = "probe"

        async def run(self, context: PipelineContext) -> PipelineContext:
            async with session_factory() as session:
                fetched = await ResearchRepository(session).get(research.id)
            assert fetched is not None
            seen_mid_run.append(fetched.status)
            context.research.status = ResearchStatus.COMPLETED
            return context

    def _runner(*, on_progress: ProgressListener | None = None) -> PipelineRunner:
        return PipelineRunner([_SetsStatusStep(), _ProbeStep()], on_progress=on_progress)

    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_pipeline_runner", _runner)
    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_resumed_pipeline_runner", _runner)

    processed = await run_once(session_factory)

    assert processed is True
    assert seen_mid_run == [ResearchStatus.DISCOVERING]


async def test_run_once_marks_job_and_research_failed_on_pipeline_error(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan §10 Phase 13's error contract: a mid-run crash must not be silently
    swallowed, marked as success, or leave the research stuck looking queued."""
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)

    def _boom(research: Research, **_kwargs: object) -> None:
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_pipeline_context_for", _boom)

    processed = await run_once(session_factory)
    assert processed is True

    async with session_factory() as session:
        job_status = await JobRepository(session).get_status(job_id)
        fetched = await ResearchRepository(session).get(research.id)

    assert job_status == "failed"
    assert fetched is not None
    assert fetched.status == ResearchStatus.FAILED
    failure = fetched.diagnostics.failure
    assert failure is not None
    assert failure.kind is FailureKind.UNEXPECTED_ERROR
    assert failure.step == "worker"
    assert "pipeline exploded" in failure.detail
    assert fetched.results == []


def _snapshot(name: str, supporters: int) -> Result:
    return Result(
        entity_id=f"state:{name.lower()}",
        entity_name=name,
        supporter_count=supporters,
        share=0.5,
        respondent_pool_size=supporters * 2,
        discussion_count=1,
        weighted_score=float(supporters),
        confidence=0.8,
    )


async def test_a_snapshot_is_persisted_while_the_run_is_still_analysing(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan §2.13: the API can only serve a provisional ranking if something
    wrote one down while the run was still going."""
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    async with session_factory() as session:
        await JobRepository(session).enqueue(research.id)

    seen_mid_run: list[list[str]] = []

    def _context(target: Research, *, settings: Settings, **kwargs: object) -> PipelineContext:
        return build_pipeline_context_for(target, settings=settings, **kwargs)  # type: ignore[arg-type]

    class _EmitsSnapshots:
        """Stands in for comment analysis: two batches, two snapshots."""

        name = "analysis"

        async def run(self, context: PipelineContext) -> PipelineContext:
            context.research.status = ResearchStatus.ANALYZING
            listener = context.on_partial_results
            assert listener is not None, "the worker gave the pipeline nowhere to report"
            for batches, supporters in ((1, 2), (2, 5)):
                await listener(
                    PartialResults(
                        results=[_snapshot("Alaska", supporters)],
                        weak_results=[],
                        batches_completed=batches,
                        comments_analysed=batches * 20,
                    )
                )
                async with session_factory() as session:
                    fetched = await ResearchRepository(session).get(research.id)
                assert fetched is not None
                seen_mid_run.append(
                    [f"{r.entity_name}:{r.supporter_count}" for r in fetched.results]
                )
            context.research.status = ResearchStatus.COMPLETED
            return context

    def _runner(*, on_progress: ProgressListener | None = None) -> PipelineRunner:
        return PipelineRunner([_EmitsSnapshots()], on_progress=on_progress)

    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_pipeline_context_for", _context)
    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_pipeline_runner", _runner)
    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_resumed_pipeline_runner", _runner)

    assert await run_once(session_factory) is True

    assert seen_mid_run == [["Alaska:2"], ["Alaska:5"]]


async def test_a_snapshot_that_arrives_out_of_order_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan §2.13.2: a snapshot covering fewer batches, landing after one
    covering more, would make the counts on screen go *down* — and that is
    the single promise which makes showing them at all defensible."""
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    async with session_factory() as session:
        await JobRepository(session).enqueue(research.id)

    persisted: list[int] = []

    def _context(target: Research, *, settings: Settings, **kwargs: object) -> PipelineContext:
        return build_pipeline_context_for(target, settings=settings, **kwargs)  # type: ignore[arg-type]

    class _EmitsOutOfOrder:
        name = "analysis"

        async def run(self, context: PipelineContext) -> PipelineContext:
            listener = context.on_partial_results
            assert listener is not None
            for batches, supporters in ((5, 9), (3, 4), (6, 11)):
                await listener(
                    PartialResults(
                        results=[_snapshot("Alaska", supporters)],
                        weak_results=[],
                        batches_completed=batches,
                        comments_analysed=batches * 20,
                    )
                )
                async with session_factory() as session:
                    fetched = await ResearchRepository(session).get(research.id)
                assert fetched is not None
                persisted.append(fetched.results[0].supporter_count)
            context.research.status = ResearchStatus.COMPLETED
            return context

    def _runner(*, on_progress: ProgressListener | None = None) -> PipelineRunner:
        return PipelineRunner([_EmitsOutOfOrder()], on_progress=on_progress)

    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_pipeline_context_for", _context)
    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_pipeline_runner", _runner)
    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_resumed_pipeline_runner", _runner)

    assert await run_once(session_factory) is True

    # The stale snapshot changed nothing: 9 stood until 11 replaced it.
    assert persisted == [9, 9, 11]
    assert persisted == sorted(persisted)


async def test_a_run_cancelled_after_a_snapshot_keeps_the_evidence_it_had(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan §2.13.3: cancelling stops the reading, it does not un-read what was
    already read. The alternative is charging for the analysis and showing an
    empty page for it."""
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)
    async with session_factory() as session:
        await JobRepository(session).request_cancel(job_id)

    def _context(target: Research, *, settings: Settings, **kwargs: object) -> PipelineContext:
        return build_pipeline_context_for(target, settings=settings, **kwargs)  # type: ignore[arg-type]

    class _SnapshotsThenIsCancelled:
        name = "analysis"

        async def run(self, context: PipelineContext) -> PipelineContext:
            context.research.status = ResearchStatus.ANALYZING
            listener = context.on_partial_results
            assert listener is not None
            await listener(
                PartialResults(
                    results=[_snapshot("Alaska", 6)],
                    weak_results=[_snapshot("Vermont", 2)],
                    batches_completed=3,
                    comments_analysed=60,
                )
            )
            return context

    def _runner(*, on_progress: ProgressListener | None = None) -> PipelineRunner:
        # Cancellation is checked between steps, so the analysis step runs to
        # completion and the aggregation that would have followed never does.
        return PipelineRunner([_SnapshotsThenIsCancelled()], on_progress=on_progress)

    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_pipeline_context_for", _context)
    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_pipeline_runner", _runner)
    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_resumed_pipeline_runner", _runner)

    assert await run_once(session_factory) is True

    async with session_factory() as session:
        fetched = await ResearchRepository(session).get(research.id)
    assert fetched is not None
    assert fetched.status is ResearchStatus.CANCELLED
    assert [r.entity_name for r in fetched.results] == ["Alaska"]
    assert [r.entity_name for r in fetched.weak_results] == ["Vermont"]
