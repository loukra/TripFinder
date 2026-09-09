"""Canned discovery/comment fixtures for FakeSourceAdapter (plan §9).

Two documents, five comments, three users favoring "Alaska" and two favoring
"Oregon" — enough to exercise ranking with more than one entity.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import HttpUrl

from tripfinder.domain.models import Comment, SourceDocument

_CREATED_AT = datetime(2025, 6, 1, tzinfo=UTC)


def fixture_documents() -> list[SourceDocument]:
    return [
        SourceDocument(
            id="post1",
            source="fake",
            title="Most underrated state for nature?",
            url=HttpUrl("https://reddit.com/r/travel/post1"),
            subreddit="travel",
            created_at=_CREATED_AT,
            comment_count=3,
        ),
        SourceDocument(
            id="post2",
            source="fake",
            title="Hidden gem national parks",
            url=HttpUrl("https://reddit.com/r/travel/post2"),
            subreddit="travel",
            created_at=_CREATED_AT,
            comment_count=2,
        ),
    ]


def fixture_comments() -> dict[str, list[Comment]]:
    return {
        "post1": [
            Comment(
                id="c1",
                source_document_id="post1",
                user_id="u1",
                body="Alaska is amazing for nature, so underrated!",
                created_at=_CREATED_AT,
                permalink=HttpUrl("https://reddit.com/r/travel/post1/c1"),
            ),
            Comment(
                id="c2",
                source_document_id="post1",
                user_id="u2",
                body="Yeah Alaska is incredible, totally agree.",
                created_at=_CREATED_AT,
                permalink=HttpUrl("https://reddit.com/r/travel/post1/c2"),
            ),
            Comment(
                id="c3",
                source_document_id="post1",
                user_id="u3",
                body="I'd say Oregon over Alaska honestly.",
                created_at=_CREATED_AT,
                permalink=HttpUrl("https://reddit.com/r/travel/post1/c3"),
            ),
        ],
        "post2": [
            Comment(
                id="c4",
                source_document_id="post2",
                user_id="u4",
                body="Alaska for sure, nothing beats it.",
                created_at=_CREATED_AT,
                permalink=HttpUrl("https://reddit.com/r/travel/post2/c4"),
            ),
            Comment(
                id="c5",
                source_document_id="post2",
                user_id="u5",
                body="Oregon has amazing coastline too.",
                created_at=_CREATED_AT,
                permalink=HttpUrl("https://reddit.com/r/travel/post2/c5"),
            ),
        ],
    }
