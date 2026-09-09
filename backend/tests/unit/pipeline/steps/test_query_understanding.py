from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.analysis.query_understanding import (
    CLARIFICATION_QUESTION,
    DEFAULT_REJECTION_REASON,
    EntityGranularityCandidate,
    QueryUnderstandingResponse,
)
from tripfinder.domain.config import QueryUnderstandingConfig, ResearchBudget, ResearchConfig
from tripfinder.domain.models import (
    Comment,
    EntityType,
    GeoScope,
    Research,
    ResearchStatus,
    SourceDocument,
)
from tripfinder.domain.ports import SourceSearchQuery
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.query_understanding import QueryUnderstandingStep


class _ForbiddenSourceAdapter:
    """A SourceAdapter that fails the test if Query Understanding ever calls it."""

    name = "forbidden"

    async def health_check(self) -> bool:
        raise AssertionError("Query Understanding must never touch the source adapter")

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        raise AssertionError("Query Understanding must never touch the source adapter")

    async def fetch_document(self, document_id: str) -> SourceDocument:
        raise AssertionError("Query Understanding must never touch the source adapter")

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        raise AssertionError("Query Understanding must never touch the source adapter")


def _context(
    response: QueryUnderstandingResponse, *, config: ResearchConfig | None = None
) -> PipelineContext:
    research = Research(
        original_query="Most underrated US destinations for nature",
        created_at=datetime.now(UTC),
        status=ResearchStatus.PENDING,
        research_config=config or ResearchConfig(),
    )
    llm = FakeLLMProvider({QueryUnderstandingResponse: response})
    return PipelineContext(research=research, source=_ForbiddenSourceAdapter(), llm=llm)


async def test_confident_query_produces_a_plan_directly() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=True,
        normalized_query="most underrated us states for nature",
        scope=GeoScope(type="country", value="United States"),
        topic="nature",
        criteria=["underrated"],
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.92)
        ],
        seed_queries=["underrated US states nature"],
        candidate_subreddits=["travel", "roadtrip"],
    )

    context = await QueryUnderstandingStep().run(_context(response))

    plan = context.data["plan"]
    assert plan.entity_granularity == EntityType.STATE
    assert plan.granularity_confidence == 0.92
    assert plan.scope == GeoScope(type="country", value="United States")
    assert plan.topic == "nature"
    assert plan.criteria == ["underrated"]
    assert context.research.normalized_query == "most underrated us states for nature"
    assert context.research.status == ResearchStatus.DISCOVERING
    assert "clarification_request" not in context.data
    assert "rejection_reason" not in context.data


async def test_ambiguous_query_produces_a_clarification_request() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=True,
        normalized_query="most underrated us destinations for nature",
        scope=GeoScope(type="country", value="United States"),
        topic="nature",
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.5),
            EntityGranularityCandidate(entity_granularity=EntityType.PARK, confidence=0.45),
            EntityGranularityCandidate(entity_granularity=EntityType.TOWN, confidence=0.4),
        ],
    )

    context = await QueryUnderstandingStep().run(_context(response))

    clarification = context.data["clarification_request"]
    assert clarification.question == CLARIFICATION_QUESTION
    assert clarification.allow_grouped is True
    assert [option.entity_granularity for option in clarification.options] == [
        EntityType.STATE,
        EntityType.PARK,
        EntityType.TOWN,
    ]
    assert all(option.label for option in clarification.options)
    assert context.research.status == ResearchStatus.NEEDS_CLARIFICATION
    assert "plan" not in context.data
    # Normalized query is not committed until a plan actually exists.
    assert context.research.normalized_query is None


async def test_clarification_deduplicates_repeated_candidate_granularities() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=True,
        normalized_query="underrated us places",
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.5),
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.3),
        ],
    )

    context = await QueryUnderstandingStep().run(_context(response))

    clarification = context.data["clarification_request"]
    assert [option.entity_granularity for option in clarification.options] == [EntityType.STATE]


async def test_no_candidates_at_all_falls_back_to_clarification() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=True,
        normalized_query="underrated us places",
        granularity_candidates=[],
    )

    context = await QueryUnderstandingStep().run(_context(response))

    assert context.research.status == ResearchStatus.NEEDS_CLARIFICATION
    assert context.data["clarification_request"].options == []


async def test_non_travel_query_is_rejected_without_touching_the_source() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=False,
        rejection_reason="This asks for a recipe, not a travel recommendation.",
        normalized_query="best pancake recipe",
    )

    context = await QueryUnderstandingStep().run(_context(response))

    assert context.research.status == ResearchStatus.REJECTED
    assert (
        context.data["rejection_reason"]
        == "This asks for a recipe, not a travel recommendation."
    )
    assert "plan" not in context.data
    assert "clarification_request" not in context.data


async def test_rejection_falls_back_to_a_default_reason_when_the_model_gives_none() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=False,
        normalized_query="best pancake recipe",
    )

    context = await QueryUnderstandingStep().run(_context(response))

    assert context.data["rejection_reason"] == DEFAULT_REJECTION_REASON


async def test_seed_queries_are_truncated_to_the_search_query_budget() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=True,
        normalized_query="underrated us states",
        scope=GeoScope(type="country", value="United States"),
        topic="nature",
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.9)
        ],
        seed_queries=["q1", "q2", "q3", "q4"],
    )
    config = ResearchConfig(budget=ResearchBudget(max_search_queries=2))

    context = await QueryUnderstandingStep().run(_context(response, config=config))

    assert context.data["plan"].seed_queries == ["q1", "q2"]


async def test_confidence_exactly_at_threshold_produces_a_plan_not_clarification() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=True,
        normalized_query="underrated us states",
        scope=GeoScope(type="country", value="United States"),
        topic="nature",
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.7)
        ],
    )
    config = ResearchConfig(query_understanding=QueryUnderstandingConfig(granularity_threshold=0.7))

    context = await QueryUnderstandingStep().run(_context(response, config=config))

    assert context.research.status == ResearchStatus.DISCOVERING
    assert context.data["plan"].granularity_confidence == 0.7


async def test_confident_response_missing_scope_raises_instead_of_guessing() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=True,
        normalized_query="underrated us states",
        topic="nature",
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.9)
        ],
    )

    with pytest.raises(ValueError, match="scope"):
        await QueryUnderstandingStep().run(_context(response))


async def test_confident_response_missing_topic_raises_instead_of_guessing() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=True,
        normalized_query="underrated us states",
        scope=GeoScope(type="country", value="United States"),
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.9)
        ],
    )

    with pytest.raises(ValueError, match="topic"):
        await QueryUnderstandingStep().run(_context(response))
