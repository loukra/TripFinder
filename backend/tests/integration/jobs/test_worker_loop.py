"""Worker loop integration tests (plan §10 Phase 3).

Runs the real queue mechanics against a real Postgres with the fake pipeline
(Phase 2) doing the "work" — the worker doesn't know or care that the
pipeline is fake.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import FailureKind, Research, ResearchStatus
from tripfinder.jobs.repository import JobRepository
from tripfinder.jobs.worker_loop import run_once, run_worker_loop
from tripfinder.persistence.repositories import ResearchRepository


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
