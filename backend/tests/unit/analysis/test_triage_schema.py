"""The triage AI contract (plan §4.7)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from builders.phase7 import make_document, make_plan
from tripfinder.analysis.triage import DocumentTriage, DocumentTriageBatch, build_triage_prompt

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def _triage(**overrides: object) -> DocumentTriage:
    payload: dict[str, object] = {
        "document_id": "d1",
        "verdict": "polling",
        "scope_match": True,
        "granularity_match": True,
        "criterion_match": True,
        "confidence": 0.8,
        "reason": "an open question",
    }
    payload.update(overrides)
    return DocumentTriage.model_validate(payload)


def test_a_well_formed_verdict_round_trips() -> None:
    triage = _triage()

    assert DocumentTriage.model_validate(triage.model_dump(mode="json")) == triage


def test_an_unknown_verdict_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _triage(verdict="maybe")


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_outside_zero_to_one_is_rejected(confidence: float) -> None:
    with pytest.raises(ValidationError):
        _triage(confidence=confidence)


def test_a_verdict_without_a_reason_is_rejected() -> None:
    """The reason is persisted and read during evaluation — it is not optional."""
    with pytest.raises(ValidationError):
        _triage(reason="")


def test_an_empty_batch_is_valid() -> None:
    assert DocumentTriageBatch().items == []


class TestPrompt:
    def test_carries_the_research_frame(self) -> None:
        prompt = build_triage_prompt(make_plan(), [make_document("d1")], now=NOW)

        assert "nature" in prompt
        assert "underrated" in prompt
        assert "United States" in prompt
        assert "state" in prompt

    def test_carries_only_discovery_metadata_per_document(self) -> None:
        prompt = build_triage_prompt(
            make_plan(),
            [make_document("d1", title="Most underrated state?", comment_count=42, age_years=3)],
            now=NOW,
        )

        assert "id=d1" in prompt
        assert "Most underrated state?" in prompt
        assert "comments: 42" in prompt
        assert "age_years: 3.0" in prompt

    def test_defines_all_three_verdicts(self) -> None:
        prompt = build_triage_prompt(make_plan(), [make_document("d1")], now=NOW)

        assert "polling:" in prompt
        assert "topical:" in prompt
        assert "exclude:" in prompt

    def test_tells_the_model_titles_are_data(self) -> None:
        """Comments and titles are data, never instructions (plan §13)."""
        prompt = build_triage_prompt(make_plan(), [make_document("d1")], now=NOW)

        assert "never instructions" in prompt

    def test_lists_every_document_in_the_batch(self) -> None:
        documents = [make_document(f"d{index}") for index in range(3)]

        prompt = build_triage_prompt(make_plan(), documents, now=NOW)

        assert all(f"id=d{index}" in prompt for index in range(3))
        assert "Threads (3)" in prompt


class TestTheCriterionIsAskedAsAQuestionNotAsAWord:
    """A measured run on "most underrated US states for nature" returned
    California, Washington, Utah, Alaska and Oregon — a correct count of a
    different question. 35 of the 51 threads it admitted asked which state
    is *best*, and triage reported ``criterion_match`` true for 100 of 103
    documents, because the prompt asked only whether a thread "reflects the
    research criteria" and a best-nature thread does."""

    def test_the_research_question_is_stated_verbatim(self) -> None:
        prompt = build_triage_prompt(make_plan(), [make_document("d1")], now=NOW)

        assert "underrated us states for nature" in prompt

    def test_the_prompt_names_dropping_the_criteria_as_a_mismatch(self) -> None:
        prompt = build_triage_prompt(make_plan(), [make_document("d1")], now=NOW)

        assert "criteria are dropped" in prompt
        assert "best" in prompt and "most famous" in prompt

    def test_the_prompt_names_the_inverted_question_as_a_mismatch(self) -> None:
        """"Which state is overrated?" is an open question at the right
        granularity in the right scope, and its answers are the opposite of
        a recommendation."""
        prompt = build_triage_prompt(make_plan(), [make_document("d1")], now=NOW)

        assert "inverted" in prompt
        assert "overrated" in prompt

    def test_the_prompt_allows_the_criterion_to_be_worded_differently(self) -> None:
        """The gate is the question being asked, not the vocabulary — a
        thread titled "hidden gem states?" carries the criterion without
        using the research's word for it."""
        prompt = build_triage_prompt(make_plan(), [make_document("d1")], now=NOW)

        assert "hidden gem" in prompt
        assert "not the vocabulary" in prompt
