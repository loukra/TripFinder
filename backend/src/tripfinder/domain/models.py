"""Core domain types.

Pure data. No I/O, no framework imports — see the import-boundary test in
tests/unit/test_architecture.py.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl

from tripfinder.domain.config import ResearchConfig


class EntityType(StrEnum):
    """The tier a recommendation target belongs to (PROJECT.md §7, plan §5)."""

    COUNTRY = "country"
    REGION = "region"
    STATE = "state"
    CITY = "city"
    TOWN = "town"
    PARK = "park"
    BEACH = "beach"
    TRAIL = "trail"
    ISLAND = "island"
    OTHER = "other"


class Stance(StrEnum):
    """Signed opinion polarity (plan §2.3). Only ``POSITIVE`` counts toward supporters."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    MENTION_ONLY = "mention_only"


class ContextType(StrEnum):
    """Whether a SourceDocument is a fair vote or merely topical (plan §4.5)."""

    POLLING = "polling"
    TOPICAL = "topical"


class ResearchStatus(StrEnum):
    """Research lifecycle states (plan §7)."""

    PENDING = "pending"
    UNDERSTANDING = "understanding"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"
    DISCOVERING = "discovering"
    RETRIEVING = "retrieving"
    ANALYZING = "analyzing"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    COMPLETED_PARTIAL = "completed_partial"
    COMPLETED_DEGRADED = "completed_degraded"
    SOURCE_UNAVAILABLE = "source_unavailable"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Entity(BaseModel):
    """A generic travel destination/recommendation target (PROJECT.md §7)."""

    id: UUID = Field(default_factory=uuid4)
    canonical_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)


class User(BaseModel):
    """The source-community author, required for independent-opinion dedup (PROJECT.md §7)."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    display_name: str | None = None


class SourceDocument(BaseModel):
    """A source post/thread (PROJECT.md §7). ``context_type`` is set by triage (plan §4.7)."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    title: str
    url: HttpUrl
    subreddit: str | None = None
    created_at: datetime
    comment_count: int = Field(ge=0)
    context_type: ContextType | None = None


class Comment(BaseModel):
    """An individual source comment (PROJECT.md §7)."""

    id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    body: str
    created_at: datetime
    permalink: HttpUrl


class Opinion(BaseModel):
    """A normalized opinion derived from a comment (PROJECT.md §7, plan §2.3)."""

    id: UUID = Field(default_factory=uuid4)
    comment_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    stance: Stance
    strength: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    criteria_matches: list[str] = Field(default_factory=list)
    timestamp: datetime
    confidence: float = Field(ge=0.0, le=1.0)


class GeoScope(BaseModel):
    """The geographic bound of a research question (plan §6), e.g. a country."""

    type: str = Field(min_length=1)
    value: str = Field(min_length=1)


class ResearchPlan(BaseModel):
    """Query Understanding's confident outcome (plan §6): a research is ready to discover."""

    normalized_query: str = Field(min_length=1)
    scope: GeoScope
    entity_granularity: EntityType
    granularity_confidence: float = Field(ge=0.0, le=1.0)
    topic: str = Field(min_length=1)
    criteria: list[str] = Field(default_factory=list)
    seed_queries: list[str] = Field(default_factory=list)
    candidate_subreddits: list[str] = Field(default_factory=list)


class ClarificationOption(BaseModel):
    """One choice offered back to the user, mapped to a candidate granularity (plan §6)."""

    label: str = Field(min_length=1)
    entity_granularity: EntityType


class ClarificationRequest(BaseModel):
    """Query Understanding's ambiguous outcome (plan §2.4, §6): ask before guessing."""

    question: str = Field(min_length=1)
    options: list[ClarificationOption]
    allow_grouped: bool = True


class TriageVerdict(StrEnum):
    """Document Triage's three outcomes (plan §4.7)."""

    POLLING = "polling"
    TOPICAL = "topical"
    EXCLUDE = "exclude"


class TriageDecidedBy(StrEnum):
    """Which half of triage decided — rules short-circuit the AI call (plan §4.7)."""

    RULE = "rule"
    AI = "ai"


class TriageDecision(BaseModel):
    """One document's verdict *and its reason* (plan §4.7 mitigation 1).

    Persisted for every triaged document, so a thin result is always
    explainable rather than merely thin (plan §0.1).
    """

    document_id: str = Field(min_length=1)
    verdict: TriageVerdict
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    decided_by: TriageDecidedBy
    scope_match: bool = True
    granularity_match: bool = True
    criterion_match: bool = True
    downgraded_for_low_confidence: bool = False


class SourceHealth(BaseModel):
    """Per-adapter call accounting for one research (plan §8.1).

    Persisted into the snapshot so a degraded run can always name the
    adapter and failure kind that degraded it.
    """

    adapter: str = Field(min_length=1)
    calls_attempted: int = Field(ge=0)
    calls_succeeded: int = Field(ge=0)
    calls_failed: int = Field(ge=0)
    failure_kinds: dict[str, int] = Field(default_factory=dict)
    success_rate: float = Field(ge=0.0, le=1.0)


class SourceOutcome(StrEnum):
    """The §8.1 outcome rules' verdict on whether the corpus can be trusted."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class SuppressionReason(StrEnum):
    """The fixed vocabulary of ways this pipeline drops evidence (plan §0.1 rule 1).

    Every value names a decision the system made *about* the corpus. A
    reason that reaches the API lets the user tell "we did not look" apart
    from "there was nothing to find".
    """

    TRIAGE_EXCLUDED = "triage_excluded"
    TRIAGE_NOT_POLLING = "triage_not_polling"
    TRIAGE_NO_VERDICT = "triage_no_verdict"
    BUDGET_MAX_TOTAL_POSTS = "budget_max_total_posts"
    BUDGET_MAX_COMMENTS = "budget_max_comments"
    BUDGET_MAX_AI_ANALYSIS_ITEMS = "budget_max_ai_analysis_items"
    RETRIEVAL_SOURCE_FAILURE = "retrieval_source_failure"
    DUPLICATE_COMMENT = "duplicate_comment"
    PREFILTER_TOO_SHORT = "prefilter_too_short"
    PREFILTER_EMPTY_BODY = "prefilter_empty_body"


class Suppression(BaseModel):
    """A count of evidence dropped by one step for one reason (plan §0.1 rule 1)."""

    step: str = Field(min_length=1)
    reason: SuppressionReason
    count: int = Field(ge=0)
    detail: str | None = None


class ResearchFlag(StrEnum):
    """Conditions that make a result set worth questioning (plan §4.7 mitigation 3)."""

    LOW_POLLING_DOCUMENT_RATIO = "low_polling_document_ratio"
    BUDGET_LIMIT_REACHED = "budget_limit_reached"


class ResearchDiagnostics(BaseModel):
    """Everything §0.1 requires a research to be able to explain about itself.

    Not debug output: this is the evidence trail that keeps a suppressed run
    distinguishable from a genuinely thin one, and it is exposed through the
    API rather than left in the logs.
    """

    source_health: list[SourceHealth] = Field(default_factory=list)
    source_outcome: SourceOutcome | None = None
    triage_decisions: list[TriageDecision] = Field(default_factory=list)
    suppressions: list[Suppression] = Field(default_factory=list)
    flags: list[ResearchFlag] = Field(default_factory=list)

    def record_suppression(
        self,
        *,
        step: str,
        reason: SuppressionReason,
        count: int,
        detail: str | None = None,
    ) -> None:
        """Append a suppression, coalescing repeats of the same step+reason+detail."""
        if count <= 0:
            return
        for existing in self.suppressions:
            if existing.step == step and existing.reason == reason and existing.detail == detail:
                existing.count += count
                return
        self.suppressions.append(
            Suppression(step=step, reason=reason, count=count, detail=detail)
        )

    def raise_flag(self, flag: ResearchFlag) -> None:
        if flag not in self.flags:
            self.flags.append(flag)


class Result(BaseModel):
    """One ranked entity in a completed research (PROJECT.md §7, plan §4)."""

    entity_id: str = Field(min_length=1)
    entity_name: str = Field(min_length=1)
    supporter_count: int = Field(ge=0)
    share: float = Field(ge=0.0)
    respondent_pool_size: int = Field(ge=0)
    discussion_count: int = Field(ge=0)
    weighted_score: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str | None = None
    evidence_permalinks: list[HttpUrl] = Field(default_factory=list)


class Research(BaseModel):
    """One execution of a user's query (PROJECT.md §7). Never silently overwritten."""

    id: UUID = Field(default_factory=uuid4)
    original_query: str = Field(min_length=1)
    normalized_query: str | None = None
    created_at: datetime
    status: ResearchStatus
    research_config: ResearchConfig = Field(default_factory=ResearchConfig)
    statistics: dict[str, int] = Field(default_factory=dict)
    results: list[Result] = Field(default_factory=list)
    diagnostics: ResearchDiagnostics = Field(default_factory=ResearchDiagnostics)


HALTING_STATUSES: frozenset[ResearchStatus] = frozenset(
    {
        ResearchStatus.NEEDS_CLARIFICATION,
        ResearchStatus.REJECTED,
        ResearchStatus.SOURCE_UNAVAILABLE,
        ResearchStatus.FAILED,
        ResearchStatus.CANCELLED,
    }
)
"""States from which no further pipeline step may run (plan §7).

``source_unavailable`` is here for the reason §8.1 gives: once every adapter
has failed there is no evidence, so continuing would only build a results
object that must not exist.
"""


def is_halting(status: ResearchStatus) -> bool:
    """Whether the pipeline must stop rather than run its remaining steps."""
    return status in HALTING_STATUSES
