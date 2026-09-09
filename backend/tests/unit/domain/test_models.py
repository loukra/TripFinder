from datetime import UTC, datetime

import pytest
from pydantic import HttpUrl, ValidationError

from tripfinder.domain.models import (
    Comment,
    ContextType,
    Entity,
    EntityType,
    Opinion,
    Research,
    ResearchStatus,
    Result,
    SourceDocument,
    Stance,
    User,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _entity() -> Entity:
    return Entity(
        canonical_id="alaska",
        canonical_name="Alaska",
        entity_type=EntityType.STATE,
        aliases=["AK", "The Last Frontier"],
    )


def _user() -> User:
    return User(id="u1", source="arctic_shift", display_name="someone")


def _document() -> SourceDocument:
    return SourceDocument(
        id="post1",
        source="arctic_shift",
        title="Most underrated state for nature?",
        url=HttpUrl("https://reddit.com/r/travel/post1"),
        subreddit="travel",
        created_at=NOW,
        comment_count=42,
        context_type=ContextType.POLLING,
    )


def _comment() -> Comment:
    return Comment(
        id="c1",
        source_document_id="post1",
        user_id="u1",
        body="Alaska is totally underrated when it comes to nature.",
        created_at=NOW,
        permalink=HttpUrl("https://reddit.com/r/travel/post1/c1"),
    )


def _opinion() -> Opinion:
    return Opinion(
        comment_id="c1",
        user_id="u1",
        entity_id="alaska",
        stance=Stance.POSITIVE,
        strength=0.9,
        relevance=0.95,
        criteria_matches=["underrated"],
        timestamp=NOW,
        confidence=0.8,
    )


def _result() -> Result:
    return Result(
        entity_id="alaska",
        entity_name="Alaska",
        supporter_count=47,
        share=47 / 112,
        respondent_pool_size=112,
        discussion_count=12,
        weighted_score=41.2,
        confidence=0.9,
        explanation="Frequently recommended for untouched wilderness.",
        evidence_permalinks=[HttpUrl("https://reddit.com/r/travel/post1/c1")],
    )


def _research() -> Research:
    return Research(
        original_query="Most underrated US destinations for nature",
        normalized_query="underrated us nature destinations",
        created_at=NOW,
        status=ResearchStatus.COMPLETED,
        statistics={"posts_retrieved": 42},
        results=[_result()],
    )


@pytest.mark.parametrize(
    "build",
    [_entity, _user, _document, _comment, _opinion, _result, _research],
)
def test_round_trips_through_serialization(build: object) -> None:
    original = build()  # type: ignore[operator]
    model_cls = type(original)

    restored = model_cls.model_validate_json(original.model_dump_json())

    assert restored == original


def test_entity_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        Entity.model_validate({"canonical_name": "Alaska"})


def test_entity_rejects_invalid_entity_type() -> None:
    with pytest.raises(ValidationError):
        Entity.model_validate(
            {
                "canonical_id": "alaska",
                "canonical_name": "Alaska",
                "entity_type": "planet",
            }
        )


def test_opinion_rejects_out_of_range_strength() -> None:
    with pytest.raises(ValidationError):
        Opinion.model_validate(
            {
                "comment_id": "c1",
                "user_id": "u1",
                "entity_id": "alaska",
                "stance": "positive",
                "strength": 1.5,
                "relevance": 0.5,
                "timestamp": NOW,
                "confidence": 0.5,
            }
        )


def test_opinion_rejects_invalid_stance() -> None:
    with pytest.raises(ValidationError):
        Opinion.model_validate(
            {
                "comment_id": "c1",
                "user_id": "u1",
                "entity_id": "alaska",
                "stance": "enthusiastic",
                "strength": 0.5,
                "relevance": 0.5,
                "timestamp": NOW,
                "confidence": 0.5,
            }
        )


def test_source_document_rejects_negative_comment_count() -> None:
    with pytest.raises(ValidationError):
        SourceDocument.model_validate(
            {
                "id": "post1",
                "source": "arctic_shift",
                "title": "x",
                "url": "https://reddit.com/x",
                "created_at": NOW,
                "comment_count": -1,
            }
        )


def test_source_document_rejects_malformed_url() -> None:
    with pytest.raises(ValidationError):
        SourceDocument.model_validate(
            {
                "id": "post1",
                "source": "arctic_shift",
                "title": "x",
                "url": "not-a-url",
                "created_at": NOW,
                "comment_count": 1,
            }
        )


def test_result_rejects_negative_supporter_count() -> None:
    with pytest.raises(ValidationError):
        Result.model_validate(
            {
                "entity_id": "alaska",
                "entity_name": "Alaska",
                "supporter_count": -1,
                "share": 0.1,
                "respondent_pool_size": 10,
                "discussion_count": 1,
                "weighted_score": 1.0,
                "confidence": 0.5,
            }
        )


def test_research_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        Research.model_validate(
            {
                "original_query": "q",
                "created_at": NOW,
                "status": "not_a_real_status",
            }
        )


def test_research_rejects_empty_query() -> None:
    with pytest.raises(ValidationError):
        Research.model_validate(
            {
                "original_query": "",
                "created_at": NOW,
                "status": "pending",
            }
        )
