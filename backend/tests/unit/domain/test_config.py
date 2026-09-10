import pytest
from pydantic import ValidationError

from tripfinder.domain.config import (
    EntityResolutionConfig,
    RankingConfig,
    RankingKey,
    ResearchBudget,
    ResearchConfig,
    SourceHealthFloors,
    TriageFloors,
)


def test_research_budget_defaults_match_plan() -> None:
    budget = ResearchBudget()

    assert budget.max_search_queries == 12
    assert budget.max_posts_per_query == 25
    assert budget.max_total_posts == 120
    assert budget.max_comments == 4000
    assert budget.max_ai_analysis_items == 1000
    assert budget.max_research_duration_seconds == 300
    assert budget.max_estimated_cost_usd == 0.50


def test_source_health_floor_defaults_match_plan() -> None:
    floors = SourceHealthFloors()

    assert floors.min_source_success_rate == 0.80
    assert floors.min_posts_retrieved == 10
    assert floors.min_comments_analyzed == 100


def test_triage_floor_defaults_match_plan() -> None:
    floors = TriageFloors()

    assert floors.min_comments_per_document == 5
    assert floors.max_document_age_years == 15
    assert floors.triage_confidence_threshold == 0.6
    assert floors.min_polling_document_ratio == 0.15


def test_entity_resolution_defaults_never_merge_below_high_confidence() -> None:
    """`PROJECT.md` §15 — the floor below which nothing is merged at all."""
    assert EntityResolutionConfig().confidence_threshold == 0.7


def test_ranking_config_defaults_match_plan() -> None:
    config = RankingConfig()

    assert config.decay_per_year == 0.10
    assert config.min_weight == 0.3
    assert config.ranking_key is RankingKey.SUPPORTER_COUNT
    assert config.minimum_independent_users == 5
    assert config.max_strong_results == 5


def test_research_config_composes_all_defaults() -> None:
    config = ResearchConfig()

    assert config.budget == ResearchBudget()
    assert config.source_health_floors == SourceHealthFloors()
    assert config.triage_floors == TriageFloors()
    assert config.entity_resolution == EntityResolutionConfig()
    assert config.ranking == RankingConfig()


def test_research_config_round_trips_through_serialization() -> None:
    config = ResearchConfig(budget=ResearchBudget(max_search_queries=5))

    restored = ResearchConfig.model_validate_json(config.model_dump_json())

    assert restored == config


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_search_queries", 0),
        ("max_posts_per_query", -1),
        ("max_estimated_cost_usd", 0.0),
    ],
)
def test_research_budget_rejects_non_positive_values(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        ResearchBudget.model_validate({field: value})


def test_source_health_floors_rejects_success_rate_above_one() -> None:
    with pytest.raises(ValidationError):
        SourceHealthFloors.model_validate({"min_source_success_rate": 1.5})


def test_triage_floors_rejects_negative_ratio() -> None:
    with pytest.raises(ValidationError):
        TriageFloors.model_validate({"min_polling_document_ratio": -0.1})


def test_entity_resolution_rejects_a_threshold_above_one() -> None:
    """A threshold nothing can clear would silently resolve nothing at all."""
    with pytest.raises(ValidationError):
        EntityResolutionConfig.model_validate({"confidence_threshold": 1.5})


def test_ranking_config_rejects_a_relevance_threshold_above_one() -> None:
    with pytest.raises(ValidationError):
        RankingConfig.model_validate({"relevance_threshold": 1.5})


def test_ranking_config_rejects_a_non_positive_strong_results_cap() -> None:
    with pytest.raises(ValidationError):
        RankingConfig.model_validate({"max_strong_results": 0})
