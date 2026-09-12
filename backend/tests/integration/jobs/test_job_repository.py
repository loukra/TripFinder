"""Job queue integration tests (plan §1 job queue, §10 Phase 3).

Real Postgres via testcontainers. ``SELECT ... FOR UPDATE SKIP LOCKED``
claim semantics and stale-job requeueing are the two behaviors that make the
queue safe for a polling worker.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import Research, ResearchStatus
from tripfinder.jobs.repository import JobNotFoundError, JobRepository
from tripfinder.persistence.repositories import ResearchRepository


async def _create_research(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> Research:
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    return research


async def test_enqueue_and_claim_next(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = await _create_research(session_factory, make_research)

    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)

    async with session_factory() as session:
        job = await JobRepository(session).claim_next()

    assert job is not None
    assert job.id == job_id
    assert job.research_id == research.id


async def test_claim_next_returns_none_when_queue_is_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        job = await JobRepository(session).claim_next()

    assert job is None


async def test_a_claimed_job_is_not_claimed_again(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = await _create_research(session_factory, make_research)
    async with session_factory() as session:
        await JobRepository(session).enqueue(research.id)

    async with session_factory() as session:
        first_claim = await JobRepository(session).claim_next()
    async with session_factory() as session:
        second_claim = await JobRepository(session).claim_next()

    assert first_claim is not None
    assert second_claim is None


async def test_mark_succeeded_updates_status(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = await _create_research(session_factory, make_research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)

    async with session_factory() as session:
        await JobRepository(session).mark_succeeded(job_id)

    async with session_factory() as session:
        assert await JobRepository(session).get_status(job_id) == "succeeded"


async def test_mark_failed_updates_status_and_records_error(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = await _create_research(session_factory, make_research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)

    async with session_factory() as session:
        await JobRepository(session).mark_failed(job_id, "boom")

    async with session_factory() as session:
        assert await JobRepository(session).get_status(job_id) == "failed"


async def test_operations_on_an_unknown_job_id_raise(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(JobNotFoundError):
            await JobRepository(session).mark_succeeded(uuid4())


async def test_requeue_stale_recovers_a_crashed_worker_job(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """Plan §10 Phase 3 acceptance: a worker crash mid-run leaves recoverable state."""
    research = await _create_research(session_factory, make_research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)

    async with session_factory() as session:
        claimed = await JobRepository(session).claim_next()
    assert claimed is not None
    assert claimed.id == job_id
    # Simulate a worker crash: the job is never marked succeeded or failed.

    async with session_factory() as session:
        assert await JobRepository(session).get_status(job_id) == "claimed"

    async with session_factory() as session:
        requeued = await JobRepository(session).requeue_stale(older_than=timedelta(seconds=0))
    assert requeued == 1

    async with session_factory() as session:
        assert await JobRepository(session).get_status(job_id) == "pending"

    # Another worker (or the same one, restarted) can now pick it back up.
    async with session_factory() as session:
        reclaimed = await JobRepository(session).claim_next()
    assert reclaimed is not None
    assert reclaimed.id == job_id

    # The crashed attempt never touched the research aggregate itself.
    async with session_factory() as session:
        fetched = await ResearchRepository(session).get(research.id)
    assert fetched is not None
    assert fetched.status == ResearchStatus.PENDING


async def test_get_for_research_returns_the_most_recent_job(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = await _create_research(session_factory, make_research)
    async with session_factory() as session:
        first_job_id = await JobRepository(session).enqueue(research.id)
    async with session_factory() as session:
        second_job_id = await JobRepository(session).enqueue(research.id)

    async with session_factory() as session:
        job = await JobRepository(session).get_for_research(research.id)

    assert job is not None
    assert job.id == second_job_id
    assert job.id != first_job_id


async def test_get_for_research_returns_none_when_nothing_was_ever_enqueued(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = await _create_research(session_factory, make_research)

    async with session_factory() as session:
        job = await JobRepository(session).get_for_research(research.id)

    assert job is None


async def test_request_cancel_flags_a_claimed_job_without_changing_its_status(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """Plan §10 Phase 13: flagging a running job does not itself stop it — the worker
    notices ``cancel_requested_at`` between pipeline steps."""
    research = await _create_research(session_factory, make_research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)
    async with session_factory() as session:
        await JobRepository(session).claim_next()

    async with session_factory() as session:
        assert await JobRepository(session).is_cancel_requested(job_id) is False

    async with session_factory() as session:
        await JobRepository(session).request_cancel(job_id)

    async with session_factory() as session:
        assert await JobRepository(session).is_cancel_requested(job_id) is True
        assert await JobRepository(session).get_status(job_id) == "claimed"


async def test_mark_cancelled_updates_status(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = await _create_research(session_factory, make_research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)

    async with session_factory() as session:
        await JobRepository(session).mark_cancelled(job_id)

    async with session_factory() as session:
        assert await JobRepository(session).get_status(job_id) == "cancelled"


async def test_requeue_stale_leaves_recently_claimed_jobs_alone(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = await _create_research(session_factory, make_research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)
    async with session_factory() as session:
        await JobRepository(session).claim_next()

    async with session_factory() as session:
        requeued = await JobRepository(session).requeue_stale(older_than=timedelta(hours=1))
    assert requeued == 0

    async with session_factory() as session:
        assert await JobRepository(session).get_status(job_id) == "claimed"


async def test_a_heartbeat_keeps_a_slow_run_out_of_the_queue(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """The difference between recovering a crash and starting a second
    pipeline on top of a live one. A run is minutes long and its last step
    can be a slow model call; a timeout alone cannot tell that from a dead
    worker, and handing such a job to a second worker spends two budgets on
    one research."""
    research = await _create_research(session_factory, make_research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)
    async with session_factory() as session:
        claimed = await JobRepository(session).claim_next()
    assert claimed is not None and claimed.claim_token is not None

    async with session_factory() as session:
        assert await JobRepository(session).heartbeat(job_id, claim_token=claimed.claim_token)

    async with session_factory() as session:
        # Long past the claim, but the worker has just said it is alive.
        requeued = await JobRepository(session).requeue_stale(older_than=timedelta(seconds=0.5))
    assert requeued == 0
    async with session_factory() as session:
        assert await JobRepository(session).get_status(job_id) == "claimed"


async def test_a_worker_that_lost_its_lease_cannot_finish_the_job(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """A stalled worker coming back must not report on a run another worker
    has already been handed."""
    research = await _create_research(session_factory, make_research)
    async with session_factory() as session:
        job_id = await JobRepository(session).enqueue(research.id)
    async with session_factory() as session:
        first = await JobRepository(session).claim_next()
    assert first is not None and first.claim_token is not None

    async with session_factory() as session:
        assert await JobRepository(session).requeue_stale(older_than=timedelta(seconds=0)) == 1
    async with session_factory() as session:
        second = await JobRepository(session).claim_next()
    assert second is not None and second.claim_token is not None
    assert second.claim_token != first.claim_token

    async with session_factory() as session:
        kept = await JobRepository(session).mark_succeeded(job_id, claim_token=first.claim_token)
    assert kept is False
    async with session_factory() as session:
        assert await JobRepository(session).get_status(job_id) == "claimed"

    async with session_factory() as session:
        stale = await JobRepository(session).heartbeat(job_id, claim_token=first.claim_token)
    assert stale is False

    # The worker that actually holds the lease still finishes normally.
    async with session_factory() as session:
        assert await JobRepository(session).mark_succeeded(job_id, claim_token=second.claim_token)
    async with session_factory() as session:
        assert await JobRepository(session).get_status(job_id) == "succeeded"
