"""Research endpoints — thin API on the fake pipeline (plan §10 Phase 3.5).

Only what the walking skeleton needs: submit a query, poll its status, read
its results once complete. The full contract (clarify, evidence, cancel) is
plan §11 / Phase 13 — later phases add it as the pipeline steps it depends on
land.

Two §8.1 obligations are enforced at this boundary rather than left to the
frontend, because they are promises about what a number means: a
``source_unavailable`` research has no results object at all, and a
``completed_degraded`` one has no percentages.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tripfinder.api.dependencies import get_session
from tripfinder.api.messages import percentages_suppressed, status_message
from tripfinder.api.schemas import (
    ResearchCreateRequest,
    ResearchCreateResponse,
    ResearchResultsResponse,
    ResearchStatusResponse,
    ResultItem,
    SourceUnavailableError,
)
from tripfinder.domain.models import Research, ResearchStatus
from tripfinder.jobs.repository import JobRepository
from tripfinder.persistence.repositories import ResearchRepository

router = APIRouter(prefix="/api/research", tags=["research"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=ResearchCreateResponse, status_code=201)
async def create_research(
    body: ResearchCreateRequest, session: SessionDep
) -> ResearchCreateResponse:
    research = Research(
        original_query=body.query,
        created_at=datetime.now(UTC),
        status=ResearchStatus.PENDING,
    )
    await ResearchRepository(session).create(research)
    await JobRepository(session).enqueue(research.id)
    return ResearchCreateResponse(id=research.id, status=research.status)


@router.get("/{research_id}", response_model=ResearchStatusResponse)
async def get_research(research_id: UUID, session: SessionDep) -> ResearchStatusResponse:
    research = await _get_or_404(research_id, session)
    return ResearchStatusResponse(
        id=research.id,
        status=research.status,
        message=status_message(research.status),
        statistics=research.statistics,
        diagnostics=research.diagnostics,
    )


@router.get("/{research_id}/results", response_model=ResearchResultsResponse)
async def get_research_results(
    research_id: UUID, session: SessionDep
) -> ResearchResultsResponse:
    research = await _get_or_404(research_id, session)
    if research.status is ResearchStatus.SOURCE_UNAVAILABLE:
        # §8.1 rule 1: every adapter failed, so there is no evidence and no
        # results object — only an error naming the adapters that failed.
        raise HTTPException(
            status_code=409,
            detail=SourceUnavailableError(
                status=research.status,
                message=status_message(research.status),
                adapters=research.diagnostics.source_health,
            ).model_dump(mode="json"),
        )

    suppress_share = percentages_suppressed(research.status)
    return ResearchResultsResponse(
        id=research.id,
        status=research.status,
        message=status_message(research.status),
        percentages_suppressed=suppress_share,
        results=[
            ResultItem.from_domain(result, suppress_share=suppress_share)
            for result in research.results
        ],
    )


async def _get_or_404(research_id: UUID, session: AsyncSession) -> Research:
    research = await ResearchRepository(session).get(research_id)
    if research is None:
        raise HTTPException(status_code=404, detail="research not found")
    return research
