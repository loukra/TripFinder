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
* **Provisional results** (plan §2.13). ``on_partial_results`` persists each
  snapshot the analysis step produces, by the same route and for the same
  reason: minutes of silence with evidence already in hand. Two rules govern
  it. A snapshot that does not advance the sequence number is refused, so
  the counts a client reads can never go backwards (§2.13.2); and only
  ``results``/``weak_results`` are written, never a status, a statistic or a
  diagnostic — the run's record is always the output of the full step 8-12
  pass, which lands here moments later by the ordinary route.
* **The lease** (plan §1's job queue). A claimed job is held by a heartbeat
  for as long as the pipeline runs, and handed back to the queue if the
  heartbeat stops — which is what turns a killed worker from "this run is
  stranded at `analyzing` for ever" into "another worker picks it up". The
  timeout alone would not be safe with more than one worker: it would hand a
  slow-but-alive run to a second one. The heartbeat says which of the two a
  quiet job is, and the claim token stops a worker that was declared dead
  from finishing a job somebody else has taken over.
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
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import FailureKind, ResearchStatus
from tripfinder.jobs.repository import JobRepository
from tripfinder.persistence.repositories import ResearchRepository
from tripfinder.pipeline.base import PartialResults, ProgressEvent
from tripfinder.pipeline.real_pipeline import (
    build_pipeline_context_for,
    build_pipeline_runner,
    build_resumed_pipeline_runner,
    is_resuming,
)
from tripfinder.settings import Settings

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 2.0

DEFAULT_HEARTBEAT_SECONDS = 15.0
"""How often a worker says it is still alive."""

DEFAULT_LEASE_SECONDS = 90.0
"""How long a job may go unheard from before the queue takes it back.

Six heartbeats. A run is minutes long and its last step can be a slow model
call, so the number that matters is not how long the work takes — it is how
long a *living* worker can go without touching the row.
"""


async def run_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
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

    async def _hold_lease(claim_token: UUID) -> None:
        """Say we are alive, until the job is done or the lease is taken."""
        while True:
            await asyncio.sleep(heartbeat_seconds)
            async with session_factory() as session:
                held = await JobRepository(session).heartbeat(job.id, claim_token=claim_token)
            if not held:
                logger.warning(
                    "worker: lost the lease on job %s — another worker has it now", job.id
                )
                return

    token = job.claim_token
    lease = (
        asyncio.create_task(_hold_lease(token))
        if token is not None and heartbeat_seconds > 0
        else None
    )

    context = None
    last_snapshot_sequence = 0
    try:

        async def _persist_partial(partial: PartialResults) -> None:
            nonlocal last_snapshot_sequence
            if partial.batches_completed <= last_snapshot_sequence:
                # An older snapshot, overtaken on its way here. Writing it
                # would make the counts on screen go down (plan §2.13.2).
                return
            last_snapshot_sequence = partial.batches_completed
            research.results = partial.results
            research.weak_results = partial.weak_results
            async with session_factory() as session:
                await ResearchRepository(session).save(research)

        context = build_pipeline_context_for(
            research, settings=settings, on_partial_results=_persist_partial
        )
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
            await JobRepository(session).mark_failed(job.id, str(exc), claim_token=token)
        return True
    finally:
        if lease is not None:
            lease.cancel()
        if context is not None:
            await _aclose_if_supported(context.source)

    async with session_factory() as session:
        if context.research.status is ResearchStatus.CANCELLED:
            kept = await JobRepository(session).mark_cancelled(job.id, claim_token=token)
        else:
            kept = await JobRepository(session).mark_succeeded(job.id, claim_token=token)
        # A worker that lost its lease is reporting on a run another worker
        # is already redoing. Writing the research row here would overwrite
        # whatever that one has produced since.
        if kept:
            await ResearchRepository(session).save(context.research)
        else:
            logger.warning(
                "worker: discarding the result of job %s — its lease was taken over", job.id
            )
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
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
) -> None:
    """Poll for jobs forever, or up to ``max_iterations`` times (for tests)."""
    settings = settings if settings is not None else Settings.from_env()
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        # Before claiming anything new: hand back whatever a dead worker was
        # holding. Every loop, not only at startup — the worker that dies is
        # not always the one that restarts.
        async with session_factory() as session:
            recovered = await JobRepository(session).requeue_stale(
                older_than=timedelta(seconds=lease_seconds)
            )
        if recovered:
            logger.warning("worker: returned %d stranded job(s) to the queue", recovered)

        processed = await run_once(
            session_factory, settings=settings, heartbeat_seconds=heartbeat_seconds
        )
        if not processed:
            await asyncio.sleep(poll_interval_seconds)
        iterations += 1
