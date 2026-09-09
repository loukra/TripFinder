"""Canned discovery/comment fixtures for FakeSourceAdapter (plan §9).

Two documents, five comments, three users favoring "Alaska" and two favoring
"Oregon" — enough to exercise ranking with more than one entity.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import HttpUrl

from tripfinder.domain.models import Comment, SourceDocument

_CREATED_AT = datetime(2025, 6, 1, tzinfo=UTC)


def _permalink(path: str) -> HttpUrl:
    return HttpUrl(f"https://reddit.com/r/travel/{path}")


def _document(document_id: str, title: str, *, comment_count: int) -> SourceDocument:
    return SourceDocument(
        id=document_id,
        source="fake",
        title=title,
        url=_permalink(document_id),
        subreddit="travel",
        created_at=_CREATED_AT,
        comment_count=comment_count,
    )


def _comment(comment_id: str, document_id: str, user_id: str, body: str) -> Comment:
    return Comment(
        id=comment_id,
        source_document_id=document_id,
        user_id=user_id,
        body=body,
        created_at=_CREATED_AT,
        permalink=_permalink(f"{document_id}/{comment_id}"),
    )


def fixture_documents() -> list[SourceDocument]:
    return [
        _document("post1", "Most underrated state for nature?", comment_count=3),
        _document("post2", "Hidden gem national parks", comment_count=2),
    ]


def fixture_comments() -> dict[str, list[Comment]]:
    return {
        "post1": [
            _comment("c1", "post1", "u1", "Alaska is amazing for nature, so underrated!"),
            _comment("c2", "post1", "u2", "Yeah Alaska is incredible, totally agree."),
            _comment("c3", "post1", "u3", "I'd say Oregon over Alaska honestly."),
        ],
        "post2": [
            _comment("c4", "post2", "u4", "Alaska for sure, nothing beats it."),
            _comment("c5", "post2", "u5", "Oregon has amazing coastline too."),
        ],
    }
