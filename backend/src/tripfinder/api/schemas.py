"""Research API DTOs (plan §11).

The API exposes domain concepts only — no Arctic Shift or Reddit structures
leak through (``PROJECT.md`` §25).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from tripfinder.domain.models import (
    ClarificationRequest,
    EntityType,
    ResearchDiagnostics,
    ResearchFailure,
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
    query: str
    """What the user typed.

    Added in 14.9 (plan §2.15) because a run is now reachable at its own URL
    by someone who did not start it — from history, from a bookmark, from a
    reload. Such a page has no memory of the question, and a ranking whose
    question is missing is a ranking of nothing in particular.
    """
    normalized_query: str | None = None
    created_at: datetime | None = None
    """When the run was started — the date a history entry is listed under."""
    statistics: dict[str, int]
    diagnostics: ResearchDiagnostics
    """What the run suppressed and why — exposed, not merely logged (plan §0.1 rule 2)."""
    clarification: ClarificationRequest | None = None
    """Set only while ``status`` is ``needs_clarification`` — answer via ``/clarify`` (plan §6)."""


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
    provisional: bool = False
    """Whether this ranking is still unfinished (plan §2.13).

    A provisional response is also distinguishable **without** reading this
    flag, and §2.13.3 requires it to be: every ``share`` is ``null`` rather
    than a number, so a screenshot, a cached response or a client that never
    heard of this field cannot render an unfinished ranking as a settled
    one. The flag is what a client that *does* know can label.
    """
    results: list[ResultItem]
    """Strong recommendations — `§4.4`'s threshold, capped, never padded."""
    weak_results: list[ResultItem] = Field(default_factory=list)
    """Everything ranked below the headline list, in the same order.

    Persisted since Phase 11 and exposed here because a provisional run
    usually has nothing else to show: nobody clears five supporters in the
    first wave of batches, and §4.4 forbids padding the strong list to hide
    that. The honest early picture is "candidates so far" (plan §2.13.1).

    Two different situations land here, and a reader must be able to tell
    them apart: an entity **below** ``minimum_independent_users``, which is
    not yet a recommendation, and one above it that merely fell outside
    §4.4's cap of five headline results. Describing the second as though it
    were the first says something false about a real count — which is why
    the threshold travels with the response.
    """
    minimum_independent_users: int = 0
    """§4.4's strong-recommendation threshold for this run.

    Config, not a constant (plan §1.1), so the view cannot hard-code it —
    and without it the view cannot say *why* an entity is in
    ``weak_results`` without guessing.
    """


class ResearchListItem(BaseModel):
    """One run as the history page lists it (plan §2.15, Phase 14.9).

    A line of history, not a miniature results page. ``status`` is what
    separates a run that finished from one that was cut short, failed or
    cancelled — §0.1 rule 4 again, one status ahead of the click rather
    than after it — and ``message`` is the same §7.1 wording the run's own
    page uses, so the list cannot describe an outcome in words the page
    contradicts.

    ``result_count`` is ``None`` — not ``0`` — for a run with no results
    page. Zero would say *this run looked and found nothing*, which is the
    sentence plan §0.1 exists to prevent a broken run from borrowing.
    """

    id: UUID
    query: str
    """What the user typed. The normalised form is ``normalized_query``."""
    normalized_query: str | None
    created_at: datetime
    status: ResearchStatus
    message: str
    result_count: int | None


class ResearchListResponse(BaseModel):
    """A page of past runs, newest first."""

    total: int
    limit: int
    offset: int
    runs: list[ResearchListItem]


class SourceUnavailableError(BaseModel):
    """The machine-readable error §8.1 rule 1 requires — and no results object."""

    status: ResearchStatus
    message: str
    adapters: list[SourceHealth]


class ResearchFailedError(BaseModel):
    """A failed run's machine-readable error — the §8.1 rule 1 shape, for §0.1 rule 3.

    ``failure`` is what separates this from a thin result: it names the
    thing that went wrong instead of leaving an empty list to imply that
    nobody had an opinion.
    """

    status: ResearchStatus
    message: str
    failure: ResearchFailure | None


class ResearchNotReadyError(BaseModel):
    """A research that has not yet reached, or will never reach, a results page.

    Covers every status besides ``source_unavailable`` and ``failed`` (which
    have their own richer errors above): still running short of analysis,
    ``needs_clarification``, ``rejected``, or ``cancelled`` with nothing to
    show — plan §7.1's "No" column, minus the two that already name their
    own cause and the two §2.13.3 moved out of it.
    """

    status: ResearchStatus
    message: str


class ClarifyRequest(BaseModel):
    """Answers a ``ClarificationRequest`` by picking one offered granularity (plan §6).

    ``allow_grouped`` ("show all tiers, grouped") is not implemented — every
    prior phase's aggregation produces one ranked list per research, and
    building the multi-list version is out of this phase's scope.
    """

    entity_granularity: EntityType


class ClarifyResponse(BaseModel):
    id: UUID
    status: ResearchStatus


class EvidenceResponse(BaseModel):
    """Paginated evidence permalinks for one ranked entity (plan §11)."""

    entity_id: str
    entity_name: str
    total: int
    limit: int
    offset: int
    permalinks: list[HttpUrl]
