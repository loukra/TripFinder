from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.analysis.query_understanding import (
    CLARIFICATION_QUESTION,
    DEFAULT_REJECTION_REASON,
    GLOBAL_SCOPE,
    OFF_TOPIC_REJECTION_REASON,
    EntityGranularityCandidate,
    QueryUnderstandingResponse,
)
from tripfinder.domain.config import QueryUnderstandingConfig, ResearchBudget, ResearchConfig
from tripfinder.domain.models import (
    Comment,
    EntityType,
    GeoScope,
    GranularityConfidence,
    PendingPlan,
    Research,
    ResearchStatus,
    SourceDocument,
)
from tripfinder.domain.ports import WebSearchHit, WebSearchQuery
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.query_understanding import (
    QueryUnderstandingStep,
    build_plan_from_pending,
)


class _ForbiddenSourceAdapter:
    """A SourceAdapter that fails the test if Query Understanding ever calls it."""

    name = "forbidden"

    async def health_check(self) -> bool:
        raise AssertionError("Query Understanding must never touch the source adapter")

    async def fetch_documents(self, document_ids: Sequence[str]) -> Sequence[SourceDocument]:
        raise AssertionError("Query Understanding must never touch the source adapter")

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        raise AssertionError("Query Understanding must never touch the source adapter")


class _ForbiddenSearchProvider:
    """A WebSearchProvider that fails the test if Query Understanding calls it."""

    name = "forbidden"

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        raise AssertionError("Query Understanding must never touch the search provider")


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
    return PipelineContext(
        research=research,
        source=_ForbiddenSourceAdapter(),
        search=_ForbiddenSearchProvider(),
        llm=llm,
    )


async def test_confident_query_produces_a_plan_directly() -> None:
    response = QueryUnderstandingResponse(
        is_recommendation_query=True,
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
        is_recommendation_query=True,
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
        is_recommendation_query=True,
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
        is_recommendation_query=True,
        normalized_query="underrated us places",
        granularity_candidates=[],
    )

    context = await QueryUnderstandingStep().run(_context(response))

    assert context.research.status == ResearchStatus.NEEDS_CLARIFICATION
    assert context.data["clarification_request"].options == []


async def test_non_travel_query_is_rejected_without_touching_the_source() -> None:
    response = QueryUnderstandingResponse(
        is_recommendation_query=False,
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
        is_recommendation_query=False,
        normalized_query="best pancake recipe",
    )

    context = await QueryUnderstandingStep().run(_context(response))

    assert context.data["rejection_reason"] == DEFAULT_REJECTION_REASON


async def test_seed_queries_are_truncated_to_the_search_query_budget() -> None:
    response = QueryUnderstandingResponse(
        is_recommendation_query=True,
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
        is_recommendation_query=True,
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


async def test_confident_response_missing_scope_defaults_to_global() -> None:
    """A query naming no place (plan §6) is a valid, worldwide-scoped plan — not a failure."""
    response = QueryUnderstandingResponse(
        is_recommendation_query=True,
        normalized_query="best hidden gem national parks for hiking",
        topic="hiking",
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.PARK, confidence=0.9)
        ],
    )

    context = await QueryUnderstandingStep().run(_context(response))

    assert context.data["plan"].scope == GLOBAL_SCOPE
    assert context.research.status == ResearchStatus.DISCOVERING


async def test_confident_response_missing_topic_raises_instead_of_guessing() -> None:
    response = QueryUnderstandingResponse(
        is_recommendation_query=True,
        normalized_query="underrated us states",
        scope=GeoScope(type="country", value="United States"),
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.9)
        ],
    )

    with pytest.raises(ValueError, match="topic"):
        await QueryUnderstandingStep().run(_context(response))


async def test_an_ambiguous_query_persists_a_pending_plan_and_clarification_on_research() -> None:
    """Plan §6, Phase 13: this is what survives the gap until ``/clarify`` answers it."""
    response = QueryUnderstandingResponse(
        is_recommendation_query=True,
        normalized_query="most underrated us destinations for nature",
        scope=GeoScope(type="country", value="United States"),
        topic="nature",
        criteria=["underrated"],
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.5),
            EntityGranularityCandidate(entity_granularity=EntityType.PARK, confidence=0.45),
        ],
        seed_queries=["underrated us nature"],
        candidate_subreddits=["travel"],
    )

    context = await QueryUnderstandingStep().run(_context(response))

    research = context.research
    assert research.clarification is context.data["clarification_request"]
    pending = research.pending_plan
    assert pending is not None
    assert pending.normalized_query == "most underrated us destinations for nature"
    assert pending.scope == GeoScope(type="country", value="United States")
    assert pending.topic == "nature"
    assert pending.criteria == ["underrated"]
    assert pending.seed_queries == ["underrated us nature"]
    assert pending.candidate_subreddits == ["travel"]
    assert [c.entity_granularity for c in pending.granularity_candidates] == [
        EntityType.STATE,
        EntityType.PARK,
    ]


async def test_a_confident_query_does_not_persist_clarification_state() -> None:
    response = QueryUnderstandingResponse(
        is_recommendation_query=True,
        normalized_query="underrated us states",
        scope=GeoScope(type="country", value="United States"),
        topic="nature",
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.9)
        ],
    )

    context = await QueryUnderstandingStep().run(_context(response))

    assert context.research.clarification is None
    assert context.research.pending_plan is None


class TestBuildPlanFromPending:
    """The other half of the resumption story — ``/clarify`` calls this directly, without
    re-running the LLM call that already produced ``PendingPlan``."""

    def _pending(self, **overrides: object) -> PendingPlan:
        defaults: dict[str, object] = dict(
            normalized_query="underrated us destinations for nature",
            scope=GeoScope(type="country", value="United States"),
            topic="nature",
            criteria=["underrated"],
            seed_queries=["q1", "q2", "q3"],
            candidate_subreddits=["travel"],
            granularity_candidates=[
                GranularityConfidence(entity_granularity=EntityType.STATE, confidence=0.5),
                GranularityConfidence(entity_granularity=EntityType.PARK, confidence=0.45),
            ],
        )
        defaults.update(overrides)
        return PendingPlan(**defaults)  # type: ignore[arg-type]

    def test_builds_a_plan_using_the_chosen_candidates_confidence(self) -> None:
        plan = build_plan_from_pending(
            self._pending(),
            entity_granularity=EntityType.PARK,
            budget=ResearchBudget(),
        )

        assert plan.entity_granularity == EntityType.PARK
        assert plan.granularity_confidence == 0.45
        assert plan.normalized_query == "underrated us destinations for nature"
        assert plan.criteria == ["underrated"]

    def test_seed_queries_are_truncated_to_the_budget(self) -> None:
        plan = build_plan_from_pending(
            self._pending(),
            entity_granularity=EntityType.STATE,
            budget=ResearchBudget(max_search_queries=2),
        )

        assert plan.seed_queries == ["q1", "q2"]

    def test_a_granularity_that_was_never_offered_raises(self) -> None:
        with pytest.raises(ValueError, match="town"):
            build_plan_from_pending(
                self._pending(),
                entity_granularity=EntityType.TOWN,
                budget=ResearchBudget(),
            )

    def test_a_missing_scope_defaults_to_global(self) -> None:
        plan = build_plan_from_pending(
            self._pending(scope=None),
            entity_granularity=EntityType.STATE,
            budget=ResearchBudget(),
        )

        assert plan.scope == GLOBAL_SCOPE

    def test_a_missing_topic_raises_instead_of_guessing(self) -> None:
        with pytest.raises(ValueError, match="topic"):
            build_plan_from_pending(
                self._pending(topic=None),
                entity_granularity=EntityType.STATE,
                budget=ResearchBudget(),
            )


class TestTwoQuestionsNotOne:
    """The method counts what people recommend; nothing in it is specific to
    destinations. "Can this be answered by counting opinions?" and "is this
    about travel?" were one boolean, so the second silently spoke for the
    first."""

    @staticmethod
    def _laptops() -> QueryUnderstandingResponse:
        return QueryUnderstandingResponse(
            is_recommendation_query=True,
            is_about_travel=False,
            normalized_query="which laptops do people actually recommend",
            topic="laptops",
            granularity_candidates=[
                EntityGranularityCandidate(entity_granularity=EntityType.OTHER, confidence=0.9)
            ],
        )

    async def test_a_non_travel_recommendation_question_runs_by_default(self) -> None:
        context = await QueryUnderstandingStep().run(_context(self._laptops()))

        assert context.research.status == ResearchStatus.DISCOVERING
        assert context.data["plan"].topic == "laptops"

    async def test_the_travel_restriction_rejects_it_when_switched_on(self) -> None:
        config = ResearchConfig(
            query_understanding=QueryUnderstandingConfig(restrict_to_travel_queries=True)
        )

        context = await QueryUnderstandingStep().run(_context(self._laptops(), config=config))

        assert context.research.status == ResearchStatus.REJECTED
        assert context.data["rejection_reason"] == OFF_TOPIC_REJECTION_REASON

    async def test_what_cannot_be_answered_by_counting_is_rejected_either_way(self) -> None:
        """The restriction is about subject matter. This is about method:
        no set of candidates to rank means nothing to count, travel or not."""
        response = QueryUnderstandingResponse(
            is_recommendation_query=False,
            is_about_travel=True,
            rejection_reason="This asks for one fact, not for what people recommend.",
            normalized_query="how tall is the eiffel tower",
        )

        for restrict in (False, True):
            config = ResearchConfig(
                query_understanding=QueryUnderstandingConfig(restrict_to_travel_queries=restrict)
            )
            context = await QueryUnderstandingStep().run(_context(response, config=config))

            assert context.research.status == ResearchStatus.REJECTED
            assert context.data["rejection_reason"] == (
                "This asks for one fact, not for what people recommend."
            )
