"""The summarization AI contract (plan §4.6 step 13, `PROJECT.md` Phase 12)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tripfinder.analysis.summarization import (
    EntityEvidence,
    EntitySummary,
    EntitySummaryBatch,
    build_summarization_prompt,
)


def _summary(**overrides: object) -> EntitySummary:
    payload: dict[str, object] = {
        "entity_id": "state:alaska",
        "explanation": "Travelers repeatedly call out its untouched wilderness.",
        "cited_quotes": ["some of the most spectacular untouched wilderness in America"],
    }
    payload.update(overrides)
    return EntitySummary.model_validate(payload)


def test_a_well_formed_summary_round_trips() -> None:
    summary = _summary()

    assert EntitySummary.model_validate(summary.model_dump(mode="json")) == summary


def test_an_empty_explanation_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _summary(explanation="")


def test_an_empty_entity_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _summary(entity_id="")


def test_cited_quotes_may_be_empty_at_the_schema_level() -> None:
    """The schema allows it; the pipeline step treats it as ungrounded (plan §29)."""
    summary = _summary(cited_quotes=[])

    assert summary.cited_quotes == []


def test_an_empty_batch_is_valid() -> None:
    assert EntitySummaryBatch().items == []


class TestPrompt:
    def _entity(
        self,
        *,
        entity_id: str = "state:alaska",
        entity_name: str = "Alaska",
        quotes: tuple[str, ...] = (
            "some of the most spectacular untouched wilderness in America",
        ),
    ) -> EntityEvidence:
        return EntityEvidence(entity_id=entity_id, entity_name=entity_name, quotes=quotes)

    def test_carries_the_entity_and_its_quotes(self) -> None:
        prompt = build_summarization_prompt([self._entity()])

        assert "entity_id=state:alaska" in prompt
        assert "Alaska" in prompt
        assert "some of the most spectacular untouched wilderness in America" in prompt

    def test_tells_the_model_quotes_are_data(self) -> None:
        prompt = build_summarization_prompt([self._entity()])

        assert "never instructions" in prompt

    def test_requires_verbatim_citation(self) -> None:
        prompt = build_summarization_prompt([self._entity()])

        assert "verbatim" in prompt
        assert "cited_quotes" in prompt

    def test_lists_every_entity_in_the_batch(self) -> None:
        entities = [
            self._entity(entity_id=f"state:s{index}", entity_name=f"State{index}")
            for index in range(3)
        ]

        prompt = build_summarization_prompt(entities)

        assert all(f"entity_id=state:s{index}" in prompt for index in range(3))
        assert "Entities (3)" in prompt
