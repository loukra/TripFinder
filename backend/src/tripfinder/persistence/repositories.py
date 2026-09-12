"""Research repository (PROJECT.md §23, plan §10 Phase 3).

Converts between the domain ``Research`` aggregate and its persisted row. A
repeated search creates a new row — ``create`` never overwrites (PROJECT.md
§7).

Since 14.9 it also reads the table the other way round: not one run by id,
but a page of runs newest first (plan §2.15). That read deliberately does
**not** build ``Research`` aggregates. A history page needs a question, a
date and an outcome per row; loading every ranking, every diagnostic and
every triage decision to print a line of text would make the list cost more
than the run it lists. :class:`ResearchSummary` is that projection, and the
two JSONB blobs are counted in the database rather than shipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tripfinder.domain.config import ResearchConfig
from tripfinder.domain.models import (
    ClarificationRequest,
    PendingPlan,
    Research,
    ResearchDiagnostics,
    ResearchPlan,
    ResearchStatus,
    Result,
    ReusedAnswer,
)
from tripfinder.persistence.orm import ResearchRow


def _to_row(research: Research) -> ResearchRow:
    return ResearchRow(
        id=research.id,
        original_query=research.original_query,
        normalized_query=research.normalized_query,
        created_at=research.created_at,
        status=research.status.value,
        research_config=research.research_config.model_dump(mode="json"),
        statistics=research.statistics,
        results=[result.model_dump(mode="json") for result in research.results],
        weak_results=[result.model_dump(mode="json") for result in research.weak_results],
        diagnostics=research.diagnostics.model_dump(mode="json"),
        clarification=_dump(research.clarification),
        pending_plan=_dump(research.pending_plan),
        resume_plan=_dump(research.resume_plan),
        plan=_dump(research.plan),
        plan_fingerprint=research.plan_fingerprint,
        reused=_dump(research.reused),
    )


def _to_domain(row: ResearchRow) -> Research:
    return Research(
        id=row.id,
        original_query=row.original_query,
        normalized_query=row.normalized_query,
        created_at=row.created_at,
        status=ResearchStatus(row.status),
        research_config=ResearchConfig.model_validate(row.research_config),
        statistics=row.statistics,
        results=[Result.model_validate(result) for result in row.results],
        weak_results=[Result.model_validate(result) for result in row.weak_results],
        diagnostics=ResearchDiagnostics.model_validate(row.diagnostics),
        clarification=_load(ClarificationRequest, row.clarification),
        pending_plan=_load(PendingPlan, row.pending_plan),
        resume_plan=_load(ResearchPlan, row.resume_plan),
        plan=_load(ResearchPlan, row.plan),
        plan_fingerprint=row.plan_fingerprint,
        reused=_load(ReusedAnswer, row.reused),
    )


def _dump(
    model: ClarificationRequest | PendingPlan | ResearchPlan | ReusedAnswer | None,
) -> dict[str, Any] | None:
    return model.model_dump(mode="json") if model is not None else None


def _load[T: (ClarificationRequest, PendingPlan, ResearchPlan, ReusedAnswer)](
    model_type: type[T], value: dict[str, Any] | None
) -> T | None:
    return model_type.model_validate(value) if value is not None else None


@dataclass(frozen=True)
class ResearchSummary:
    """One row of history: enough to list a run, not enough to read it.

    ``result_count`` counts the ranked entities the row holds; it is not a
    statement that they may be *shown*. A run that failed after aggregation
    has results in its row and no results page (plan §7.1), and deciding
    that is the API boundary's job, not this layer's.
    """

    id: UUID
    original_query: str
    normalized_query: str | None
    created_at: datetime
    status: ResearchStatus
    result_count: int
    weak_result_count: int
    reused: ReusedAnswer | None
    """Set when this run showed an earlier run's answer (plan §2.15).

    Loaded for the list because the date on it is what stops a history row
    from presenting a March answer under today's date — small enough to
    ship with a projection built to avoid shipping the big JSONB blobs."""


class ResearchNotFoundError(LookupError):
    """Raised when saving a research aggregate that was never created."""


class ResearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, research: Research) -> None:
        self._session.add(_to_row(research))
        await self._session.commit()

    async def get(self, research_id: UUID) -> Research | None:
        row = await self._session.get(ResearchRow, research_id)
        return _to_domain(row) if row is not None else None

    async def save(self, research: Research) -> None:
        """Persist the current state of an already-created research."""
        row = await self._session.get(ResearchRow, research.id)
        if row is None:
            raise ResearchNotFoundError(f"research {research.id} was never created")
        row.normalized_query = research.normalized_query
        row.status = research.status.value
        row.statistics = research.statistics
        row.results = [result.model_dump(mode="json") for result in research.results]
        row.weak_results = [result.model_dump(mode="json") for result in research.weak_results]
        row.diagnostics = research.diagnostics.model_dump(mode="json")
        row.clarification = _dump(research.clarification)
        row.pending_plan = _dump(research.pending_plan)
        row.resume_plan = _dump(research.resume_plan)
        row.plan = _dump(research.plan)
        row.plan_fingerprint = research.plan_fingerprint
        row.reused = _dump(research.reused)
        await self._session.commit()

    async def list_recent(self, *, limit: int, offset: int = 0) -> list[ResearchSummary]:
        """One page of past runs, newest first (plan §2.15, Phase 14.9).

        ``id`` breaks ties on ``created_at`` so that paging through the
        table cannot show the same run twice or skip one when two runs
        share a timestamp.
        """
        rows = await self._session.execute(
            select(
                ResearchRow.id,
                ResearchRow.original_query,
                ResearchRow.normalized_query,
                ResearchRow.created_at,
                ResearchRow.status,
                func.jsonb_array_length(ResearchRow.results).label("result_count"),
                func.jsonb_array_length(ResearchRow.weak_results).label("weak_result_count"),
                ResearchRow.reused,
            )
            .order_by(ResearchRow.created_at.desc(), ResearchRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [
            ResearchSummary(
                id=row.id,
                original_query=row.original_query,
                normalized_query=row.normalized_query,
                created_at=row.created_at,
                status=ResearchStatus(row.status),
                result_count=row.result_count,
                weak_result_count=row.weak_result_count,
                reused=_load(ReusedAnswer, row.reused),
            )
            for row in rows.all()
        ]

    async def find_by_fingerprint(
        self, *, fingerprint: str, not_before: datetime
    ) -> Research | None:
        """The newest run carrying this reuse key inside the window (plan §2.15).

        ``completed`` and "not itself a reuse" are in the query rather than
        left to the caller, and neither is policy: without them the newest
        matching row wins, so a question asked twice this morning would be
        offered yesterday's good answer only when this morning's failure did
        not exist. They narrow *which* row comes back. Whether it may be
        used is re-decided by ``AnswerReuseStep`` against the run itself,
        where the rules are readable without a database.
        """
        row = (
            await self._session.execute(
                select(ResearchRow)
                .where(
                    ResearchRow.plan_fingerprint == fingerprint,
                    ResearchRow.created_at >= not_before,
                    ResearchRow.status == ResearchStatus.COMPLETED.value,
                    ResearchRow.reused.is_(None),
                )
                .order_by(ResearchRow.created_at.desc(), ResearchRow.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def count(self) -> int:
        """How many runs the table holds — the denominator ``list_recent`` pages through."""
        total = await self._session.execute(select(func.count()).select_from(ResearchRow))
        return total.scalar_one()
