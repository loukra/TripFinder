"""Postgres-backed job queue (plan §1 — no Redis; plan §10 Phase 3, cancellation Phase 13).

``claim_next`` uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple worker
processes can poll the same table without double-claiming a job.
**A claim is a lease, not a flag.** ``requeue_stale`` is what makes a worker
crash recoverable: a job left ``claimed`` past a deadline is handed back to
the queue rather than lost. On a timeout alone that is only safe with one
worker — a slow-but-alive run would be handed to a second one, and two
pipelines would spend two budgets and write the same research row. So a
claim carries two more things:

* ``heartbeat_at``, touched while the job is being worked on, which is what
  makes "no worker" distinguishable from "slow worker";
* ``claim_token``, refreshed on every claim. Finishing or heartbeating a job
  requires holding its current token, so a worker that was declared dead and
  then comes back cannot write over the run somebody else has since taken
  over. It is told it lost the lease instead.

Cancellation (plan §10 Phase 13) has two paths, chosen by where a job is when
the request arrives. A ``pending`` job has no worker looking at it yet, so
the API cancels it outright. A ``claimed`` job may already be mid-run, and
nothing here can interrupt a step in flight (plan §7, ``PipelineRunner``'s
``should_cancel`` docstring) — ``cancel_requested_at`` only flags it, and the
worker notices between steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tripfinder.persistence.orm import ResearchJobRow


@dataclass(frozen=True)
class Job:
    id: UUID
    research_id: UUID
    status: str = "claimed"
    claim_token: UUID | None = None
    """The lease this claim holds. Required to heartbeat or finish it."""


class JobNotFoundError(LookupError):
    """Raised when finishing a job id that was never enqueued."""


def _to_job(row: ResearchJobRow) -> Job:
    return Job(
        id=row.id,
        research_id=row.research_id,
        status=row.status,
        claim_token=row.claim_token,
    )


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, research_id: UUID) -> UUID:
        job_id = uuid4()
        self._session.add(
            ResearchJobRow(
                id=job_id,
                research_id=research_id,
                status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await self._session.commit()
        return job_id

    async def claim_next(self) -> Job | None:
        stmt = (
            select(ResearchJobRow)
            .where(ResearchJobRow.status == "pending")
            .order_by(ResearchJobRow.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        now = datetime.now(UTC)
        row.status = "claimed"
        row.claimed_at = now
        row.heartbeat_at = now
        row.claim_token = uuid4()
        await self._session.commit()
        return _to_job(row)

    async def heartbeat(self, job_id: UUID, *, claim_token: UUID) -> bool:
        """Say this job is still being worked on. False means the lease is gone.

        A worker that has lost its lease — because it stalled long enough to
        look dead and the job was requeued — must stop, or it will finish a
        run another worker is already redoing.
        """
        row = await self._session.get(ResearchJobRow, job_id)
        if row is None or row.status != "claimed" or row.claim_token != claim_token:
            return False
        row.heartbeat_at = datetime.now(UTC)
        await self._session.commit()
        return True

    async def mark_succeeded(self, job_id: UUID, *, claim_token: UUID | None = None) -> bool:
        return await self._finish(job_id, "succeeded", claim_token=claim_token)

    async def mark_failed(
        self, job_id: UUID, error: str, *, claim_token: UUID | None = None
    ) -> bool:
        return await self._finish(job_id, "failed", error=error, claim_token=claim_token)

    async def mark_cancelled(self, job_id: UUID, *, claim_token: UUID | None = None) -> bool:
        return await self._finish(job_id, "cancelled", claim_token=claim_token)

    async def _finish(
        self,
        job_id: UUID,
        status: str,
        *,
        error: str | None = None,
        claim_token: UUID | None = None,
    ) -> bool:
        """Record a job's outcome. ``False`` means the lease was lost first.

        A caller that holds a token is a worker reporting on a run it did;
        if the job has since been requeued and re-claimed, that report is
        about a run somebody else is redoing and must not land. The API's
        own cancel path holds no token and is not subject to this — it is
        acting for the user, not finishing work.
        """
        row = await self._get_or_raise(job_id)
        if claim_token is not None and row.claim_token != claim_token:
            return False
        row.status = status
        row.finished_at = datetime.now(UTC)
        if error is not None:
            row.error = error
        await self._session.commit()
        return True

    async def request_cancel(self, job_id: UUID) -> None:
        """Flag a ``claimed`` job for cancellation; the worker notices between steps."""
        row = await self._get_or_raise(job_id)
        row.cancel_requested_at = datetime.now(UTC)
        await self._session.commit()

    async def is_cancel_requested(self, job_id: UUID) -> bool:
        row = await self._get_or_raise(job_id)
        return row.cancel_requested_at is not None

    async def get_status(self, job_id: UUID) -> str:
        row = await self._get_or_raise(job_id)
        return row.status

    async def get_for_research(self, research_id: UUID) -> Job | None:
        """The most recent job enqueued for this research, if any."""
        stmt = (
            select(ResearchJobRow)
            .where(ResearchJobRow.research_id == research_id)
            .order_by(ResearchJobRow.created_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_job(row) if row is not None else None

    async def requeue_stale(self, *, older_than: timedelta) -> int:
        """Hand back jobs whose worker has stopped saying it is alive.

        The deadline is measured against the last heartbeat, falling back to
        the claim for a job claimed before this column existed. A job whose
        worker is merely slow keeps its lease, however long the run takes:
        that is the whole difference between recovering a crash and starting
        a second pipeline on top of a live one.
        """
        deadline = datetime.now(UTC) - older_than
        last_seen = func.coalesce(ResearchJobRow.heartbeat_at, ResearchJobRow.claimed_at)
        stmt = select(ResearchJobRow).where(
            ResearchJobRow.status == "claimed",
            last_seen < deadline,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        for row in rows:
            row.status = "pending"
            row.claimed_at = None
            row.heartbeat_at = None
            # The lease is void: whoever held it can no longer finish this job.
            row.claim_token = None
        await self._session.commit()
        return len(rows)

    async def _get_or_raise(self, job_id: UUID) -> ResearchJobRow:
        row = await self._session.get(ResearchJobRow, job_id)
        if row is None:
            raise JobNotFoundError(f"job {job_id} was never enqueued")
        return row
