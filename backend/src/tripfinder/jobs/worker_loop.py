"""Polling worker loop (plan §1 job queue, §10 Phase 3).

Runs the fake pipeline (Phase 2) against a persisted ``Research`` for each
claimed job. Wiring in the real pipeline is later phases' work — this loop's
job is the queue mechanics: claim, run, persist, mark done, and leave
recoverable state on failure.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.jobs.repository import JobRepository
from tripfinder.persistence.repositories import ResearchRepository
from tripfinder.pipeline.fake_pipeline import (
    build_fake_pipeline_context_for,
    build_fake_pipeline_runner,
)

DEFAULT_POLL_INTERVAL_SECONDS = 2.0


async def run_once(session_factory: async_sessionmaker[AsyncSession]) -> bool:
    """Claim and run at most one job. Returns whether a job was claimed."""
    async with session_factory() as session:
        job = await JobRepository(session).claim_next()
    if job is None:
        return False

    async with session_factory() as session:
        research = await ResearchRepository(session).get(job.research_id)
    # research_jobs.research_id is a foreign key into research.id, so a
    # claimed job's research row is guaranteed to exist.
    assert research is not None

    try:
        context = build_fake_pipeline_context_for(research)
        context = await build_fake_pipeline_runner().run(context)
    except Exception as exc:
        async with session_factory() as session:
            await JobRepository(session).mark_failed(job.id, str(exc))
        return True

    async with session_factory() as session:
        await ResearchRepository(session).save(context.research)
        await JobRepository(session).mark_succeeded(job.id)
    return True


async def run_worker_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_iterations: int | None = None,
) -> None:
    """Poll for jobs forever, or up to ``max_iterations`` times (for tests)."""
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        processed = await run_once(session_factory)
        if not processed:
            await asyncio.sleep(poll_interval_seconds)
        iterations += 1
