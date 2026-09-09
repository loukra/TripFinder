"""Research budget and floor configuration (plan §1.1).

Every value here is config, not a constant buried in a step. Each research
persists the ``ResearchConfig`` it actually ran with (PROJECT.md §21).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchBudget(BaseModel):
    """Hard limits on how much a single research is allowed to cost (plan §1.1)."""

    max_search_queries: int = Field(default=12, gt=0)
    max_posts_per_query: int = Field(default=25, gt=0)
    max_total_posts: int = Field(default=120, gt=0)
    max_comments: int = Field(default=4000, gt=0)
    max_ai_analysis_items: int = Field(default=1000, gt=0)
    max_research_duration_seconds: int = Field(default=300, gt=0)
    max_estimated_cost_usd: float = Field(default=0.50, gt=0.0)


class SourceHealthFloors(BaseModel):
    """Below these, a research fails outright rather than reporting (plan §1.1, §8.1)."""

    min_source_success_rate: float = Field(default=0.80, ge=0.0, le=1.0)
    min_posts_retrieved: int = Field(default=10, ge=0)
    min_comments_analyzed: int = Field(default=100, ge=0)


class TriageFloors(BaseModel):
    """Document triage thresholds (plan §1.1, §4.7)."""

    min_comments_per_document: int = Field(default=5, ge=0)
    max_document_age_years: int = Field(default=15, gt=0)
    triage_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    min_polling_document_ratio: float = Field(default=0.15, ge=0.0, le=1.0)


class QueryUnderstandingConfig(BaseModel):
    """Query Understanding thresholds (plan §2.4, §6)."""

    granularity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class ResearchConfig(BaseModel):
    """The full configuration a research run persists (PROJECT.md §21)."""

    budget: ResearchBudget = Field(default_factory=ResearchBudget)
    source_health_floors: SourceHealthFloors = Field(default_factory=SourceHealthFloors)
    triage_floors: TriageFloors = Field(default_factory=TriageFloors)
    query_understanding: QueryUnderstandingConfig = Field(default_factory=QueryUnderstandingConfig)
