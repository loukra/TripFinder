"""Research API DTOs (plan §11).

The API exposes domain concepts only — no Arctic Shift or Reddit structures
leak through (``PROJECT.md`` §25).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from tripfinder.domain.models import (
    ResearchDiagnostics,
    ResearchStatus,
    Result,
    SourceHealth,
)


class ResearchCreateRequest(BaseModel):
    query: str = Field(min_length=1)


class ResearchCreateResponse(BaseModel):
    id: UUID
    status: ResearchStatus


class ResearchStatusResponse(BaseModel):
    id: UUID
    status: ResearchStatus
    message: str
    statistics: dict[str, int]
    diagnostics: ResearchDiagnostics
    """What the run suppressed and why — exposed, not merely logged (plan §0.1 rule 2)."""


class ResultItem(BaseModel):
    """One ranked entity as the API renders it.

    ``share`` is nullable where the domain ``Result`` is not: a degraded run
    has no meaningful denominator, so §8.1 rule 2 suppresses percentages and
    the API returns ``null`` rather than a number the user should not read.
    """

    entity_id: str
    entity_name: str
    supporter_count: int
    share: float | None
    respondent_pool_size: int
    discussion_count: int
    weighted_score: float
    confidence: float
    explanation: str | None
    evidence_permalinks: list[HttpUrl]

    @classmethod
    def from_domain(cls, result: Result, *, suppress_share: bool) -> ResultItem:
        return cls(
            entity_id=result.entity_id,
            entity_name=result.entity_name,
            supporter_count=result.supporter_count,
            share=None if suppress_share else result.share,
            respondent_pool_size=result.respondent_pool_size,
            discussion_count=result.discussion_count,
            weighted_score=result.weighted_score,
            confidence=result.confidence,
            explanation=result.explanation,
            evidence_permalinks=result.evidence_permalinks,
        )


class ResearchResultsResponse(BaseModel):
    id: UUID
    status: ResearchStatus
    message: str
    percentages_suppressed: bool
    results: list[ResultItem]


class SourceUnavailableError(BaseModel):
    """The machine-readable error §8.1 rule 1 requires — and no results object."""

    status: ResearchStatus
    message: str
    adapters: list[SourceHealth]
