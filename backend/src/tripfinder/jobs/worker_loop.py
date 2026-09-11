"""Polling worker loop (plan §1 job queue, §10 Phase 3; real pipeline in Phase 13).

Runs the real pipeline (plan §10 Phase 13's composition root) against a
persisted ``Research`` for each claimed job — or, for a research resuming
after clarification (plan §6), the shorter resumed pipeline seeded with the
plan it already settled on. Tests get a faked source and LLM by pointing
``build_pipeline_context_for``/``build_pipeline_runner`` elsewhere (plan §9);
this loop does not know or care which it got.

Two things this loop owns beyond queue mechanics:

* **Cancellation** (plan §10 Phase 13). ``should_cancel`` polls the claimed
  job's ``cancel_requested_at`` flag between pipeline steps — the API sets
  it when a cancel request arrives for a job already running.
* **Progress persistence.** ``on_progress`` saves ``research.status`` after
  every step, not only once at the end — a real run against live adapters
  can take minutes, and without this the API has nothing to report but
  "pending" for the run's entire duration even while it is actively working.
* **The error contract** (plan §0.1, plan §10 Phase 13). ``PipelineRunner``
  already converts an LLM provider failure into a named, ``failed`` research;
  everything else — a bug, a mapping error, anything unexpected — used to
  leave the research stuck at ``pending`` forever while the job quietly
  failed. That is exactly the failure §0.1 forbids: not an absence of
  evidence, but a run that never looked like it stopped at all. This loop
  now marks the research ``failed`` with a named, generic cause too.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import FailureKind, ResearchStatus
from tripfinder.jobs.repository import JobRepository
from tripfinder.persistence.repositories import ResearchRepository
from tripfinder.pipeline.base import ProgressEvent
from tripfinder.pipeline.real_pipeline import (
    build_pipeline_context_for,
    build_pipeline_runner,
    build_resumed_pipeline_runner,
    is_resuming,
)
from tripfinder.settings import Settings

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 2.0


async def run_once(
    session_factory: async_sessionmaker[AsyncSession], *, settings: Settings | None = None
) -> bool:
    """Claim and run at most one job. Returns whether a job was claimed."""
    settings = settings if settings is not None else Settings.from_env()

    async with session_factory() as session:
        job = await JobRepository(session).claim_next()
    if job is None:
        return False

    async with session_factory() as session:
        research = await ResearchRepository(session).get(job.research_id)
    # research_jobs.research_id is a foreign key into research.id, so a
    # claimed job's research row is guaranteed to exist.
    assert research is not None

    async def _should_cancel() -> bool:
        async with session_factory() as session:
            return await JobRepository(session).is_cancel_requested(job.id)

    context = None
    try:
        context = build_pipeline_context_for(research, settings=settings)
        pipeline_context = context

        async def _persist_progress(event: ProgressEvent) -> None:
            async with session_factory() as session:
                await ResearchRepository(session).save(pipeline_context.research)

        runner = (
            build_resumed_pipeline_runner(on_progress=_persist_progress)
            if is_resuming(research)
            else build_pipeline_runner(on_progress=_persist_progress)
        )
        context = await runner.run(context, should_cancel=_should_cancel)
    except Exception as exc:
        logger.warning(
            "worker: job %s failed outside the pipeline's own error handling: %s", job.id, exc
        )
        research.diagnostics.record_failure(
            kind=FailureKind.UNEXPECTED_ERROR, step="worker", detail=str(exc)
        )
        research.results = []
        research.status = ResearchStatus.FAILED
        async with session_factory() as session:
            await ResearchRepository(session).save(research)
            await JobRepository(session).mark_failed(job.id, str(exc))
        return True
    finally:
        if context is not None:
            await _aclose_if_supported(context.source)

    async with session_factory() as session:
        await ResearchRepository(session).save(context.research)
        if context.research.status is ResearchStatus.CANCELLED:
            await JobRepository(session).mark_cancelled(job.id)
        else:
            await JobRepository(session).mark_succeeded(job.id)
    return True


async def _aclose_if_supported(source: object) -> None:
    """Real adapters own an HTTP client that must be closed; fakes need not define one."""
    aclose = getattr(source, "aclose", None)
    if aclose is not None:
        await aclose()


async def run_worker_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings | None = None,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_iterations: int | None = None,
) -> None:
    """Poll for jobs forever, or up to ``max_iterations`` times (for tests)."""
    settings = settings if settings is not None else Settings.from_env()
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        processed = await run_once(session_factory, settings=settings)
        if not processed:
            await asyncio.sleep(poll_interval_seconds)
        iterations += 1
