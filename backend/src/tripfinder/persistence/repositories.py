"""Research repository (PROJECT.md §23, plan §10 Phase 3).

Converts between the domain ``Research`` aggregate and its persisted row. A
repeated search creates a new row — ``create`` never overwrites (PROJECT.md
§7).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
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
    )


def _dump(
    model: ClarificationRequest | PendingPlan | ResearchPlan | None,
) -> dict[str, Any] | None:
    return model.model_dump(mode="json") if model is not None else None


def _load[T: (ClarificationRequest, PendingPlan, ResearchPlan)](
    model_type: type[T], value: dict[str, Any] | None
) -> T | None:
    return model_type.model_validate(value) if value is not None else None


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
        await self._session.commit()

    async def list_all(self) -> list[Research]:
        rows = await self._session.execute(select(ResearchRow).order_by(ResearchRow.created_at))
        return [_to_domain(row) for row in rows.scalars().all()]
