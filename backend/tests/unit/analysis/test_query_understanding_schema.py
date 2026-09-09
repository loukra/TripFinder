import pytest
from pydantic import ValidationError

from tripfinder.analysis.query_understanding import (
    CLARIFICATION_QUESTION,
    DEFAULT_REJECTION_REASON,
    EntityGranularityCandidate,
    QueryUnderstandingResponse,
    build_query_understanding_prompt,
    granularity_label,
)
from tripfinder.domain.models import EntityType, GeoScope


def test_prompt_includes_the_raw_query() -> None:
    prompt = build_query_understanding_prompt("Most underrated US states for nature")

    assert "Most underrated US states for nature" in prompt


def test_granularity_label_covers_every_entity_type() -> None:
    for entity_type in EntityType:
        assert granularity_label(entity_type)


def test_response_defaults_to_no_candidates_and_no_rejection() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=True, normalized_query="underrated states"
    )

    assert response.granularity_candidates == []
    assert response.rejection_reason is None


def test_response_round_trips_with_scope_and_candidates() -> None:
    response = QueryUnderstandingResponse(
        is_travel_recommendation_query=True,
        normalized_query="underrated states",
        scope=GeoScope(type="country", value="United States"),
        topic="nature",
        criteria=["underrated"],
        granularity_candidates=[
            EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=0.9)
        ],
        seed_queries=["underrated states nature"],
        candidate_subreddits=["travel"],
    )

    restored = QueryUnderstandingResponse.model_validate_json(response.model_dump_json())

    assert restored == response


def test_response_rejects_confidence_outside_unit_range() -> None:
    with pytest.raises(ValidationError):
        EntityGranularityCandidate(entity_granularity=EntityType.STATE, confidence=1.5)


def test_constants_are_non_empty() -> None:
    assert DEFAULT_REJECTION_REASON
    assert CLARIFICATION_QUESTION
