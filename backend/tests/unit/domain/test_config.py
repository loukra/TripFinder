import pytest
from pydantic import ValidationError

from tripfinder.domain.config import (
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


def test_research_config_composes_all_defaults() -> None:
    config = ResearchConfig()

    assert config.budget == ResearchBudget()
    assert config.source_health_floors == SourceHealthFloors()
    assert config.triage_floors == TriageFloors()


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
