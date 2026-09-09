"""Research API DTOs (plan §11).

The API exposes domain concepts only — no Arctic Shift or Reddit structures
leak through (``PROJECT.md`` §25).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from tripfinder.domain.models import ResearchStatus, Result


class ResearchCreateRequest(BaseModel):
    query: str = Field(min_length=1)


class ResearchCreateResponse(BaseModel):
    id: UUID
    status: ResearchStatus


class ResearchStatusResponse(BaseModel):
    id: UUID
    status: ResearchStatus
    statistics: dict[str, int]


class ResearchResultsResponse(BaseModel):
    id: UUID
    status: ResearchStatus
    results: list[Result]
