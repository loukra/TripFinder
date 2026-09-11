from collections.abc import Callable
from typing import Any

import pytest

from tripfinder.sources.arctic_shift.mapping import (
    comment_to_domain,
    is_bot_author,
    post_to_document,
)

LoadFixture = Callable[[str], dict[str, Any]]


def test_is_bot_author_matches_automoderator_case_insensitive() -> None:
    assert is_bot_author("AutoModerator") is True
    assert is_bot_author("automoderator") is True


def test_is_bot_author_matches_hyphen_and_underscore_bot_suffix() -> None:
    assert is_bot_author("reminder-bot") is True
    assert is_bot_author("weather_bot") is True


def test_is_bot_author_matches_configured_denylist() -> None:
    assert is_bot_author("SpecialCrawler", denylist=["specialcrawler"]) is True


def test_is_bot_author_false_for_ordinary_user() -> None:
    assert is_bot_author("hikerjane") is False
    assert is_bot_author("[deleted]") is False


def test_post_to_document_maps_fields(load_fixture: LoadFixture) -> None:
    raw = load_fixture("posts_ids_batch.json")["data"][0]

    document = post_to_document(raw, source="arctic_shift")

    assert document.id == "1wbve58"
    assert document.source == "arctic_shift"
    assert document.title == "Most underrated state for nature?"
    assert (
        str(document.url)
        == "https://www.reddit.com/r/travel/comments/1wbve58/most_underrated_state_for_nature/"
    )
    assert document.subreddit == "travel"
    assert document.comment_count == 42
    assert document.created_at.year == 2024


def test_post_to_document_raises_for_missing_required_field(load_fixture: LoadFixture) -> None:
    raw = load_fixture("posts_ids_malformed_item.json")["data"][1]

    with pytest.raises(KeyError):
        post_to_document(raw, source="arctic_shift")


def test_comment_to_domain_maps_fields(load_fixture: LoadFixture) -> None:
    raw = load_fixture("comments_search_success.json")["data"][1]

    comment = comment_to_domain(raw, source_document_id="1wbve58")

    assert comment.id == "p8t0od8"
    assert comment.source_document_id == "1wbve58"
    assert comment.user_id == "hikerjane"
    assert comment.body == "Alaska is amazing for nature, so underrated!"
    assert str(comment.permalink).startswith("https://www.reddit.com/r/travel/")
    assert comment.score == 24


def test_comment_to_domain_keeps_a_zero_score_apart_from_a_missing_one(
    load_fixture: LoadFixture,
) -> None:
    """Plan §2.12: a comment nobody voted on is not a comment we know nothing about.

    Pre-filter spends the analysis budget by score (§4.6 step 6), so a
    substituted zero would silently rank an unscored comment below every
    downvoted one.
    """
    raw = load_fixture("comments_search_success.json")["data"][3]
    assert raw["score"] == 0

    assert comment_to_domain(raw, source_document_id="1wbve58").score == 0
    assert comment_to_domain({**raw, "score": None}, source_document_id="1wbve58").score is None
    unscored = {key: value for key, value in raw.items() if key != "score"}
    assert comment_to_domain(unscored, source_document_id="1wbve58").score is None


def test_comment_to_domain_ignores_an_unusable_score(load_fixture: LoadFixture) -> None:
    raw = load_fixture("comments_search_success.json")["data"][3]

    assert comment_to_domain({**raw, "score": "nonsense"}, source_document_id="d").score is None


def test_comment_to_domain_deleted_author_is_preserved_not_dropped(
    load_fixture: LoadFixture,
) -> None:
    raw = load_fixture("comments_search_success.json")["data"][2]

    comment = comment_to_domain(raw, source_document_id="1wbve58")

    assert comment.user_id == "[deleted]"
    assert comment.body == "[removed]"
