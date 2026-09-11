import pytest
from pydantic import ValidationError

from tripfinder.analysis.discovery import DiscoveryTurnResponse, build_discovery_prompt
from tripfinder.domain.models import EntityType, GeoScope, ResearchPlan


def _plan(**overrides: object) -> ResearchPlan:
    defaults: dict[str, object] = dict(
        normalized_query="underrated us states for nature",
        scope=GeoScope(type="country", value="United States"),
        entity_granularity=EntityType.STATE,
        granularity_confidence=0.9,
        topic="nature",
        criteria=["underrated"],
        seed_queries=["underrated states nature"],
        candidate_subreddits=["travel", "roadtrip"],
    )
    defaults.update(overrides)
    return ResearchPlan(**defaults)  # type: ignore[arg-type]


def test_prompt_includes_plan_details() -> None:
    prompt = build_discovery_prompt(_plan(), issued_queries=[], documents_found=0)

    assert "nature" in prompt
    assert "underrated" in prompt
    assert "United States" in prompt
    assert "state" in prompt
    assert "travel" in prompt and "roadtrip" in prompt


def test_prompt_lists_already_issued_queries() -> None:
    prompt = build_discovery_prompt(
        _plan(), issued_queries=["underrated states nature", "hidden gem parks"], documents_found=4
    )

    assert "underrated states nature" in prompt
    assert "hidden gem parks" in prompt
    assert "Reddit threads found so far: 4" in prompt


def test_prompt_names_no_issued_queries_when_none_yet() -> None:
    prompt = build_discovery_prompt(_plan(), issued_queries=[], documents_found=0)

    assert "(none yet)" in prompt


def test_prompt_asks_for_the_batch_size_it_was_given() -> None:
    prompt = build_discovery_prompt(
        _plan(), issued_queries=[], documents_found=0, queries_per_turn=5
    )

    assert "up to 5 new search queries" in prompt


def test_prompt_says_which_threads_are_worth_finding() -> None:
    """§4.5: only an open question can produce a counted opinion, and a
    discovery loop that is not told so spends its budget on trip reports —
    74 of 106 threads in the measured run."""
    prompt = build_discovery_prompt(_plan(), issued_queries=[], documents_found=0)

    assert "open question" in prompt
    assert "trip report" in prompt


def test_response_defaults_to_no_next_queries() -> None:
    response = DiscoveryTurnResponse(should_continue=False, reasoning="enough coverage gathered")

    assert response.next_queries == []


def test_response_requires_a_non_empty_reasoning() -> None:
    with pytest.raises(ValidationError):
        DiscoveryTurnResponse(should_continue=True, next_queries=["q"], reasoning="")


def test_the_turn_schema_no_longer_asks_the_model_for_a_subreddit() -> None:
    """Plan §2.11: web search needs no scope, and the ``site:`` restriction is
    the tool's job — a field the model can populate is a field it can get
    wrong."""
    assert "subreddit" not in DiscoveryTurnResponse.model_fields


def test_the_prompt_tells_the_model_not_to_write_search_operators() -> None:
    prompt = build_discovery_prompt(_plan(), issued_queries=[], documents_found=0)

    assert "do not write site:" in prompt
