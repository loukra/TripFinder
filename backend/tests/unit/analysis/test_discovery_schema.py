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


class TestTheCriteriaAreARequirementNotContext:
    """The first batched-discovery run doubled the respondent pool and
    answered a different question: "what state has the best nature" threads
    are easier to find and far busier than "which state is underrated"
    ones, and this prompt's own examples used to include a criterion-free
    *"what is your favourite and why?"*."""

    def test_the_research_question_is_stated_verbatim(self) -> None:
        prompt = build_discovery_prompt(_plan(), issued_queries=[], documents_found=0)

        assert "underrated us states for nature" in prompt

    def test_every_query_is_required_to_carry_the_criteria(self) -> None:
        prompt = build_discovery_prompt(_plan(), issued_queries=[], documents_found=0)

        assert "must carry the criteria" in prompt

    def test_the_opposite_question_is_ruled_out(self) -> None:
        prompt = build_discovery_prompt(_plan(), issued_queries=[], documents_found=0)

        assert "Never propose the opposite question" in prompt

    def test_the_prompt_offers_no_criterion_free_example_question(self) -> None:
        """The model follows the examples. A criterion-free one is an
        instruction to drift."""
        prompt = build_discovery_prompt(_plan(), issued_queries=[], documents_found=0)

        assert "what is your favourite and why" not in prompt


class TestATurnIsToldHowFarItHasDrifted:
    def test_the_off_criterion_count_reaches_the_prompt(self) -> None:
        prompt = build_discovery_prompt(
            _plan(),
            issued_queries=["best states for hiking"],
            documents_found=20,
            polling_found=14,
            topical_found=6,
            off_criterion=9,
        )

        assert "9 of them ask a different question" in prompt

    def test_a_turn_that_has_not_drifted_is_not_told_that_it_has(self) -> None:
        prompt = build_discovery_prompt(
            _plan(),
            issued_queries=["underrated states nature"],
            documents_found=20,
            polling_found=14,
            topical_found=6,
        )

        assert "14 are open questions that count and 6 are not" in prompt
        assert "ask a different question" not in prompt
