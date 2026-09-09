"""Worker loop integration tests (plan §10 Phase 3).

Runs the real queue mechanics against a real Postgres with the fake pipeline
(Phase 2) doing the "work" — the worker doesn't know or care that the
pipeline is fake.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import Research, ResearchStatus
from tripfinder.jobs.repository import JobRepository
from tripfinder.jobs.worker_loop import run_once, run_worker_loop
from tripfinder.persistence.repositories import ResearchRepository


def _research(query: str = "underrated US nature destinations") -> Research:
    return Research(
        original_query=query, created_at=datetime.now(UTC), status=ResearchStatus.PENDING
    )


async def test_run_once_processes_a_claimed_job_end_to_end(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    research = _research()
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


async def test_two_identical_searches_produce_two_distinct_completed_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Plan §10 Phase 3 acceptance, exercised end-to-end through the worker."""
    first = _research()
    second = _research()

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


async def test_run_once_marks_job_failed_and_leaves_research_untouched_on_pipeline_error(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-run failure must not be silently swallowed or marked as success."""
    research = _research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)

    def _boom(research: Research) -> None:
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr("tripfinder.jobs.worker_loop.build_fake_pipeline_context_for", _boom)

    processed = await run_once(session_factory)
    assert processed is True

    async with session_factory() as session:
        job_status = await JobRepository(session).get_status(job_id)
        fetched = await ResearchRepository(session).get(research.id)

    assert job_status == "failed"
    assert fetched is not None
    assert fetched.status == ResearchStatus.PENDING
