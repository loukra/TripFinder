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
