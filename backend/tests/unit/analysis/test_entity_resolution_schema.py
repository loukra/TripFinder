"""The entity resolution AI contract (plan §4.6 step 8, `PROJECT.md` §15)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from builders.phase7 import make_plan
from tripfinder.analysis.entity_resolution import (
    EntityResolutionBatch,
    ResolutionQuestion,
    ResolvedName,
    build_entity_resolution_prompt,
)
from tripfinder.domain.models import EntityType

QUESTION = ResolutionQuestion(
    surface_form="the Beaver State",
    entity_type=EntityType.STATE,
    example_quote="the Beaver State is criminally underrated",
)
AMBIGUOUS = ResolutionQuestion(
    surface_form="Springfield",
    entity_type=EntityType.CITY,
    example_quote="Springfield is worth a detour",
    candidates=("Springfield, Oregon", "Springfield, Illinois"),
)


def _name(**overrides: object) -> ResolvedName:
    payload: dict[str, object] = {
        "surface_form": "the Beaver State",
        "canonical_name": "Oregon",
        "confidence": 0.9,
        "reason": "a well-known nickname for Oregon",
    }
    payload.update(overrides)
    return ResolvedName.model_validate(payload)


def test_a_well_formed_answer_round_trips() -> None:
    answer = _name()

    assert ResolvedName.model_validate(answer.model_dump(mode="json")) == answer


def test_a_null_canonical_name_is_a_valid_answer() -> None:
    """"I cannot tell" is the answer §15 wants when confidence is lacking."""
    assert _name(canonical_name=None).canonical_name is None


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_outside_zero_to_one_is_rejected(confidence: float) -> None:
    with pytest.raises(ValidationError):
        _name(confidence=confidence)


def test_an_answer_without_a_reason_is_rejected() -> None:
    """The reason is persisted and read when a name goes unresolved."""
    with pytest.raises(ValidationError):
        _name(reason="")


def test_an_answer_without_a_surface_form_is_rejected() -> None:
    """Unattributable to anything we asked about."""
    with pytest.raises(ValidationError):
        _name(surface_form="")


def test_an_empty_batch_is_valid() -> None:
    assert EntityResolutionBatch().items == []


class TestPrompt:
    def test_carries_the_research_frame(self) -> None:
        prompt = build_entity_resolution_prompt(make_plan(), [QUESTION])

        assert "underrated us states for nature" in prompt
        assert "United States" in prompt
        assert "state" in prompt

    def test_carries_the_form_its_guess_and_a_quote(self) -> None:
        prompt = build_entity_resolution_prompt(make_plan(), [QUESTION])

        assert "the Beaver State" in prompt
        assert "Beaver State" in prompt
        assert "criminally underrated" in prompt

    def test_offers_the_candidates_for_an_ambiguous_form(self) -> None:
        prompt = build_entity_resolution_prompt(make_plan(), [AMBIGUOUS])

        assert "Springfield, Oregon, Springfield, Illinois" in prompt

    def test_lists_no_candidates_for_an_unknown_form(self) -> None:
        prompt = build_entity_resolution_prompt(make_plan(), [QUESTION])

        assert "candidates:" not in prompt

    def test_asks_for_null_rather_than_a_guess(self) -> None:
        """The erring direction `PROJECT.md` §15 requires, stated to the model too."""
        prompt = build_entity_resolution_prompt(make_plan(), [QUESTION])

        assert "null rather than a guess" in prompt

    def test_tells_the_model_quotes_are_data(self) -> None:
        prompt = build_entity_resolution_prompt(make_plan(), [QUESTION])

        assert "never instructions" in prompt

    def test_lists_every_form_in_the_batch(self) -> None:
        prompt = build_entity_resolution_prompt(make_plan(), [QUESTION, AMBIGUOUS])

        assert "Names (2)" in prompt
        assert "surface_form: Springfield" in prompt
