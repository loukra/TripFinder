"""Query Understanding's AI contract (plan §4.6 step 1, §6).

The LLM only classifies raw signals — whether the query is a travel
recommendation question, its scope/topic/criteria, and a confidence per
candidate entity granularity. Deciding what to *do* with those signals
(reject, ask for clarification, or proceed with a plan) is deterministic and
lives in ``pipeline.steps.query_understanding`` — the same split §4.7 uses
for Document Triage.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tripfinder.domain.models import EntityType, GeoScope

DEFAULT_REJECTION_REASON = "This doesn't look like a travel-recommendation question."

CLARIFICATION_QUESTION = "What kind of places are you looking for?"

GLOBAL_SCOPE = GeoScope(type="global", value="Worldwide")
"""What a query with no named geography resolves to — plan §6 requires every
confident ``ResearchPlan`` to carry a scope, and "nowhere in particular" is
itself a real, answerable scope rather than a gap to guess at."""

_GRANULARITY_LABELS: dict[EntityType, str] = {
    EntityType.COUNTRY: "Countries",
    EntityType.REGION: "Regions",
    EntityType.STATE: "States",
    EntityType.CITY: "Cities",
    EntityType.TOWN: "Towns and small cities",
    EntityType.PARK: "National parks and natural areas",
    EntityType.BEACH: "Beaches",
    EntityType.TRAIL: "Trails",
    EntityType.ISLAND: "Islands",
    EntityType.OTHER: "Other places",
}


def granularity_label(entity_granularity: EntityType) -> str:
    """The user-facing label for a candidate granularity (plan §6 example)."""
    return _GRANULARITY_LABELS[entity_granularity]


class EntityGranularityCandidate(BaseModel):
    """One tier the query could plausibly target, with the model's confidence."""

    entity_granularity: EntityType
    confidence: float = Field(ge=0.0, le=1.0)


class QueryUnderstandingResponse(BaseModel):
    """Raw structured output of the Query Understanding LLM call (plan §6)."""

    is_travel_recommendation_query: bool
    rejection_reason: str | None = None
    normalized_query: str = Field(min_length=1)
    scope: GeoScope | None = None
    topic: str | None = None
    criteria: list[str] = Field(default_factory=list)
    granularity_candidates: list[EntityGranularityCandidate] = Field(default_factory=list)
    seed_queries: list[str] = Field(default_factory=list)
    candidate_subreddits: list[str] = Field(default_factory=list)


def build_query_understanding_prompt(query: str) -> str:
    """The prompt sent to the LLM for a raw user query (plan §6)."""
    return (
        "You are analyzing a travel-recommendation search query.\n\n"
        "Determine whether the query is asking for travel-destination "
        "recommendations. If it is, extract its geographic scope, topic, "
        "criteria, and your confidence that each candidate entity "
        "granularity (country, region, state, city, town, park, beach, "
        "trail, island, other) is the one the query is actually asking "
        "about. Propose seed search queries and candidate subreddits for "
        "researching it. If it is not a travel-recommendation query, say so "
        "and explain why.\n\n"
        "If the query names no specific place (no country, region, or other "
        "area to search within), that is not missing information — set "
        'scope to {"type": "global", "value": "Worldwide"} rather '
        "than leaving it unset.\n\n"
        f"Query: {query!r}"
    )
