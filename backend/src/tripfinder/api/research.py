"""Research endpoints (plan §11, hardened in plan §10 Phase 13).

Four obligations are enforced at this boundary rather than left to the
frontend, because they are promises about what a number means: a
``source_unavailable`` research has no results object at all (§8.1 rule 1),
a ``completed_degraded`` one has no percentages (§8.1 rule 2), a ``failed``
one has no results object either but does name its cause (§7.1, plan §0.1
rule 3), and nothing awaiting clarification or rejected gets a results
object that could be mistaken for a finished one.

Since 14.7 a run that is still ``analyzing`` — and a cancelled run that got
that far — does get one, marked ``provisional`` and with every ``share``
null (plan §2.13.3). That is not an exception to the obligation above but an
instance of it: an unfinished ranking has to be unmistakable for a finished
one, and the way it is made unmistakable is a hole where the percentage
would be, which no client can fill in by ignoring a flag.

Cancellation (plan §10 Phase 13) has two paths depending on whether a
worker has already claimed the job: a job still queued is cancelled
outright; a job in flight is flagged, and the worker's own error contract
(``jobs/worker_loop.py``) is what actually lands it on ``cancelled`` between
pipeline steps — this endpoint cannot interrupt a step mid-call, and does
not pretend to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from tripfinder.api.dependencies import get_session
from tripfinder.api.messages import (
    is_provisional,
    percentages_suppressed,
    research_message,
    results_message,
)
from tripfinder.api.schemas import (
    ClarifyRequest,
    ClarifyResponse,
    EvidenceResponse,
    ResearchCreateRequest,
    ResearchCreateResponse,
    ResearchFailedError,
    ResearchNotReadyError,
    ResearchResultsResponse,
    ResearchStatusResponse,
    ResultItem,
    SourceUnavailableError,
)
from tripfinder.domain.models import ClarificationRequest, Research, ResearchStatus, Result
from tripfinder.jobs.repository import JobRepository
from tripfinder.persistence.repositories import ResearchRepository
from tripfinder.pipeline.steps.query_understanding import build_plan_from_pending

router = APIRouter(prefix="/api/research", tags=["research"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_RESULTS_READY_STATUSES = frozenset(
    {
        ResearchStatus.COMPLETED,
        ResearchStatus.COMPLETED_PARTIAL,
        ResearchStatus.COMPLETED_DEGRADED,
        # Plan §2.13: a run that is still analysing has real counts from
        # comments it has already read. They are served as provisional —
        # counts only, no shares — rather than withheld for five minutes.
        ResearchStatus.ANALYZING,
    }
)

_UNCANCELLABLE_STATUSES = frozenset(
    {
        ResearchStatus.COMPLETED,
        ResearchStatus.COMPLETED_PARTIAL,
        ResearchStatus.COMPLETED_DEGRADED,
        ResearchStatus.SOURCE_UNAVAILABLE,
        ResearchStatus.REJECTED,
        ResearchStatus.FAILED,
        ResearchStatus.CANCELLED,
    }
)


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
    return _status_response(research)


@router.post(
    "/{research_id}/clarify",
    response_model=ClarifyResponse,
    responses={
        404: {"description": "No research with this id"},
        409: {"description": "This research is not awaiting clarification"},
        422: {"description": "Query Understanding did not leave enough to build a plan from"},
    },
)
async def clarify_research(
    research_id: UUID, body: ClarifyRequest, session: SessionDep
) -> ClarifyResponse:
    research = await _get_or_404(research_id, session)
    if research.status is not ResearchStatus.NEEDS_CLARIFICATION:
        raise HTTPException(
            status_code=409,
            detail=f"research {research_id} is {research.status.value}, not awaiting clarification",
        )
    if research.clarification is None or research.pending_plan is None:
        raise HTTPException(
            status_code=409, detail=f"research {research_id} has no pending clarification to answer"
        )
    offered = {option.entity_granularity for option in research.clarification.options}
    if body.entity_granularity not in offered:
        raise HTTPException(
            status_code=400,
            detail=f"{body.entity_granularity.value!r} was not offered as a clarification option",
        )

    try:
        plan = build_plan_from_pending(
            research.pending_plan,
            entity_granularity=body.entity_granularity,
            budget=research.research_config.budget,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    research.resume_plan = plan
    research.normalized_query = plan.normalized_query
    research.status = ResearchStatus.DISCOVERING
    await ResearchRepository(session).save(research)
    await JobRepository(session).enqueue(research.id)
    return ClarifyResponse(id=research.id, status=research.status)


@router.post(
    "/{research_id}/cancel",
    response_model=ResearchStatusResponse,
    responses={
        404: {"description": "No research with this id"},
        409: {"description": "This research has already finished and cannot be cancelled"},
    },
)
async def cancel_research(research_id: UUID, session: SessionDep) -> ResearchStatusResponse:
    research = await _get_or_404(research_id, session)
    if research.status in _UNCANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"research {research_id} is already {research.status.value} "
                "and cannot be cancelled"
            ),
        )

    jobs = JobRepository(session)
    job = await jobs.get_for_research(research_id)
    if job is not None and job.status == "claimed":
        # Already running: flag it and let the worker notice between steps
        # (plan §10 Phase 13) — nothing here can interrupt a step in flight.
        await jobs.request_cancel(job.id)
    else:
        # Not yet claimed, or the worker already finished its run (e.g. this
        # research is paused at `needs_clarification`, whose job succeeded):
        # nothing is running, so cancellation is immediate.
        if job is not None and job.status == "pending":
            await jobs.mark_cancelled(job.id)
        research.status = ResearchStatus.CANCELLED
        await ResearchRepository(session).save(research)

    refreshed = await ResearchRepository(session).get(research_id)
    assert refreshed is not None
    return _status_response(refreshed)


@router.get(
    "/{research_id}/results",
    response_model=ResearchResultsResponse,
    responses={
        404: {"description": "No research with this id"},
        409: {"description": "This research has no results object (see plan §7.1)"},
    },
)
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
                message=_message(research),
                adapters=research.diagnostics.source_health,
            ).model_dump(mode="json"),
        )

    if research.status is ResearchStatus.FAILED:
        # §7.1: a failed run has no results page. Plan §0.1 rule 3 adds the
        # reason, so the caller can tell a broken run from a quiet one.
        raise HTTPException(
            status_code=409,
            detail=ResearchFailedError(
                status=research.status,
                message=_message(research),
                failure=research.diagnostics.failure,
            ).model_dump(mode="json"),
        )

    _require_results_ready(research)

    suppress_share = percentages_suppressed(research.status)
    return ResearchResultsResponse(
        id=research.id,
        status=research.status,
        message=results_message(research.status),
        percentages_suppressed=suppress_share,
        provisional=is_provisional(research.status),
        results=[
            ResultItem.from_domain(result, suppress_share=suppress_share)
            for result in research.results
        ],
        weak_results=[
            ResultItem.from_domain(result, suppress_share=suppress_share)
            for result in research.weak_results
        ],
        minimum_independent_users=(
            research.research_config.ranking.minimum_independent_users
        ),
    )


@router.get(
    "/{research_id}/evidence",
    response_model=EvidenceResponse,
    responses={
        404: {"description": "No research with this id, or no ranked entity with this entity_id"},
        409: {"description": "This research has no results object (see plan §7.1)"},
    },
)
async def get_research_evidence(
    research_id: UUID,
    entity_id: str,
    session: SessionDep,
    limit: Annotated[int, Query(gt=0, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvidenceResponse:
    research = await _get_or_404(research_id, session)
    _require_results_ready(research)

    result = _find_result(research, entity_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"no ranked entity {entity_id!r} in research {research_id}"
        )

    permalinks = result.evidence_permalinks
    page = permalinks[offset : offset + limit]
    return EvidenceResponse(
        entity_id=result.entity_id,
        entity_name=result.entity_name,
        total=len(permalinks),
        limit=limit,
        offset=offset,
        permalinks=page,
    )


def _message(research: Research) -> str:
    return research_message(research.status, research.diagnostics.failure)


def _visible_clarification(research: Research) -> ClarificationRequest | None:
    return research.clarification if research.status is ResearchStatus.NEEDS_CLARIFICATION else None


def _status_response(research: Research) -> ResearchStatusResponse:
    return ResearchStatusResponse(
        id=research.id,
        status=research.status,
        message=_message(research),
        statistics=research.statistics,
        diagnostics=research.diagnostics,
        clarification=_visible_clarification(research),
    )


def _holds_a_snapshot(research: Research) -> bool:
    """Whether a cancelled run has a provisional ranking worth serving (plan §2.13.3).

    §7.1 gave ``cancelled`` no results page, on the reasoning that an
    interrupted run has nothing to report. Since 14.7 that is no longer
    true: a run cancelled during analysis has already ranked the comments it
    read, and throwing that away to show an empty page is the same waste
    §2.12.2 refuses when it lets in-flight batches finish. A cancelled run
    with no snapshot behaves exactly as it did before.
    """
    return research.status is ResearchStatus.CANCELLED and bool(
        research.results or research.weak_results
    )


def _require_results_ready(research: Research) -> None:
    """Plan §7.1's "No" column, for every status not already handled by a richer error."""
    if research.status not in _RESULTS_READY_STATUSES and not _holds_a_snapshot(research):
        raise HTTPException(
            status_code=409,
            detail=ResearchNotReadyError(
                status=research.status, message=_message(research)
            ).model_dump(mode="json"),
        )


def _find_result(research: Research, entity_id: str) -> Result | None:
    for result in (*research.results, *research.weak_results):
        if result.entity_id == entity_id:
            return result
    return None


async def _get_or_404(research_id: UUID, session: AsyncSession) -> Research:
    research = await ResearchRepository(session).get(research_id)
    if research is None:
        raise HTTPException(status_code=404, detail="research not found")
    return research
