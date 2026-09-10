"""Postgres-backed job queue (plan §1 — no Redis; plan §10 Phase 3, cancellation Phase 13).

``claim_next`` uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple worker
processes can poll the same table without double-claiming a job.
``requeue_stale`` is what makes a worker crash recoverable: a job left
``claimed`` past a deadline is handed back to the queue rather than lost.

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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tripfinder.persistence.orm import ResearchJobRow


@dataclass(frozen=True)
class Job:
    id: UUID
    research_id: UUID
    status: str = "claimed"


class JobNotFoundError(LookupError):
    """Raised when finishing a job id that was never enqueued."""


def _to_job(row: ResearchJobRow) -> Job:
    return Job(id=row.id, research_id=row.research_id, status=row.status)


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
        row.status = "claimed"
        row.claimed_at = datetime.now(UTC)
        await self._session.commit()
        return _to_job(row)

    async def mark_succeeded(self, job_id: UUID) -> None:
        row = await self._get_or_raise(job_id)
        row.status = "succeeded"
        row.finished_at = datetime.now(UTC)
        await self._session.commit()

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        row = await self._get_or_raise(job_id)
        row.status = "failed"
        row.finished_at = datetime.now(UTC)
        row.error = error
        await self._session.commit()

    async def mark_cancelled(self, job_id: UUID) -> None:
        row = await self._get_or_raise(job_id)
        row.status = "cancelled"
        row.finished_at = datetime.now(UTC)
        await self._session.commit()

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
        """Reset jobs still ``claimed`` past the deadline back to ``pending``."""
        deadline = datetime.now(UTC) - older_than
        stmt = select(ResearchJobRow).where(
            ResearchJobRow.status == "claimed",
            ResearchJobRow.claimed_at < deadline,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        for row in rows:
            row.status = "pending"
            row.claimed_at = None
        await self._session.commit()
        return len(rows)

    async def _get_or_raise(self, job_id: UUID) -> ResearchJobRow:
        row = await self._session.get(ResearchJobRow, job_id)
        if row is None:
            raise JobNotFoundError(f"job {job_id} was never enqueued")
        return row
