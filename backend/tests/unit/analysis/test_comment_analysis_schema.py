"""The comment-analysis AI contract (plan §5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from builders.labeled_comments import labeled_comments, one
from builders.phase7 import make_comment, make_plan
from tripfinder.analysis.comment_analysis import (
    CommentAnalysis,
    CommentAnalysisBatch,
    EntityMention,
    build_comment_analysis_prompt,
)


def _mention(**overrides: object) -> EntityMention:
    payload: dict[str, object] = {
        "raw_text": "the UP",
        "normalized_guess": "Michigan",
        "entity_type": "state",
        "stance": "positive",
        "strength": 0.8,
        "supporting_quote": "the UP is stunning",
    }
    payload.update(overrides)
    return EntityMention.model_validate(payload)


def _analysis(**overrides: object) -> CommentAnalysis:
    payload: dict[str, object] = {
        "comment_id": "c1",
        "topic_relevance": 0.9,
        "criterion_relevance": 0.8,
        "scope_match": True,
        "overall_confidence": 0.85,
        "mentions": [_mention().model_dump(mode="json")],
        "reasoning": "recommends a state for nature",
    }
    payload.update(overrides)
    return CommentAnalysis.model_validate(payload)


def test_a_well_formed_analysis_round_trips() -> None:
    analysis = _analysis()

    assert CommentAnalysis.model_validate(analysis.model_dump(mode="json")) == analysis


def test_an_unknown_stance_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _mention(stance="enthusiastic")


def test_an_unknown_entity_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _mention(entity_type="continent")


@pytest.mark.parametrize("field", ["topic_relevance", "criterion_relevance", "overall_confidence"])
@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_scores_outside_zero_to_one_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        _analysis(**{field: value})


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_strength_outside_zero_to_one_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        _mention(strength=value)


def test_a_mention_without_a_supporting_quote_is_rejected() -> None:
    """The quote is the whole anti-fabrication mechanism — it is not optional."""
    with pytest.raises(ValidationError):
        _mention(supporting_quote="")


def test_an_analysis_with_no_mentions_is_valid() -> None:
    """A comment that recommends nothing is a real answer, not a malformed one."""
    assert _analysis(mentions=[]).mentions == []


def test_an_empty_batch_is_valid() -> None:
    assert CommentAnalysisBatch().items == []


class TestPrompt:
    def test_carries_the_research_frame(self) -> None:
        prompt = build_comment_analysis_prompt(make_plan(), [make_comment("c1")])

        assert "nature" in prompt
        assert "underrated" in prompt
        assert "United States" in prompt
        assert "state" in prompt

    def test_carries_every_comment_body_in_the_batch(self) -> None:
        comments = [make_comment(f"c{index}", body=f"body number {index}") for index in range(3)]

        prompt = build_comment_analysis_prompt(make_plan(), comments)

        assert all(f"id=c{index}" in prompt for index in range(3))
        assert all(f"body number {index}" in prompt for index in range(3))
        assert "Comments (3)" in prompt

    def test_demands_a_verbatim_quote(self) -> None:
        prompt = build_comment_analysis_prompt(make_plan(), [make_comment("c1")])

        assert "character for character" in prompt
        assert "discarded" in prompt

    def test_asks_for_meaning_rather_than_wording(self) -> None:
        """The acceptance criterion, stated to the model as well as tested in code."""
        prompt = build_comment_analysis_prompt(make_plan(), [make_comment("c1")])

        assert "Judge meaning, not wording." in prompt

    def test_tells_the_model_comments_are_data(self) -> None:
        prompt = build_comment_analysis_prompt(make_plan(), [make_comment("c1")])

        assert "never instructions" in prompt


class TestTheLabeledFixtureSet:
    """The corpus itself has to be right before anything asserted against it is."""

    def test_covers_every_label(self) -> None:
        labels = {entry.label for entry in labeled_comments()}

        assert labels == {
            "clearly_relevant",
            "indirectly_relevant",
            "irrelevant",
            "ambiguous",
            "equivalent_wording",
        }

    def test_every_quote_and_surface_form_is_verbatim(self) -> None:
        for entry in labeled_comments():
            if entry.mention is None:
                continue
            assert entry.mention.quote in entry.body, entry.id
            assert entry.mention.raw_text in entry.body, entry.id

    def test_the_equivalent_wording_comments_share_no_keyword_with_the_query(self) -> None:
        """Keyword matching cannot rescue these — only meaning can."""
        for entry in labeled_comments():
            if entry.label != "equivalent_wording":
                continue
            body = entry.body.lower()
            assert "underrated" not in body
            assert "nature" not in body
            assert entry.mention is not None
            assert entry.mention.entity.lower() not in body

    def test_every_fixture_is_a_valid_domain_comment(self) -> None:
        """Construction is the assertion — an empty id or body would not validate."""
        corpus = labeled_comments()

        assert [entry.as_comment().id for entry in corpus] == [entry.id for entry in corpus]

    def test_a_missing_fixture_raises(self) -> None:
        with pytest.raises(LookupError):
            one("c-does-not-exist")
