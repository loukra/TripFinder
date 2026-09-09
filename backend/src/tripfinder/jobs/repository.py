"""Postgres-backed job queue (plan §1 — no Redis; plan §10 Phase 3).

``claim_next`` uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple worker
processes can poll the same table without double-claiming a job.
``requeue_stale`` is what makes a worker crash recoverable: a job left
``claimed`` past a deadline is handed back to the queue rather than lost.
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


class JobNotFoundError(LookupError):
    """Raised when finishing a job id that was never enqueued."""


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
        return Job(id=row.id, research_id=row.research_id)

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

    async def get_status(self, job_id: UUID) -> str:
        row = await self._get_or_raise(job_id)
        return row.status

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
