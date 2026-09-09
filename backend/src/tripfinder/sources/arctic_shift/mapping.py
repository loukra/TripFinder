"""Raw Arctic Shift JSON -> domain types (plan §8's adapter responsibilities).

Pure functions: no I/O, no retry logic. A missing/wrong-typed field raises
``KeyError``/``TypeError``/``ValueError``/``pydantic.ValidationError`` — the
caller drops that one item and keeps going, never coercing bad data into a
plausible-looking record.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import HttpUrl

from tripfinder.domain.models import Comment, SourceDocument

_DEFAULT_BOT_DENYLIST = {"automoderator"}
_BOT_SUFFIX_RE = re.compile(r"[-_]bot$", re.IGNORECASE)

DELETED_AUTHOR = "[deleted]"


def is_bot_author(author: str, *, denylist: list[str] | None = None) -> bool:
    """Plan §8: drop AutoModerator, ``*-bot``/``*_bot`` authors, and a denylist."""
    normalized = author.strip().lower()
    if normalized in _DEFAULT_BOT_DENYLIST:
        return True
    if normalized in {name.strip().lower() for name in denylist or ()}:
        return True
    return bool(_BOT_SUFFIX_RE.search(normalized))


def _reddit_url(permalink: str) -> HttpUrl:
    return HttpUrl(f"https://www.reddit.com{permalink}")


def post_to_document(raw: dict[str, Any], *, source: str) -> SourceDocument:
    return SourceDocument(
        id=str(raw["id"]),
        source=source,
        title=raw["title"],
        url=_reddit_url(raw["permalink"]),
        subreddit=raw.get("subreddit"),
        created_at=datetime.fromtimestamp(raw["created_utc"], tz=UTC),
        comment_count=max(0, int(raw.get("num_comments") or 0)),
    )


def comment_to_domain(raw: dict[str, Any], *, source_document_id: str) -> Comment:
    return Comment(
        id=str(raw["id"]),
        source_document_id=source_document_id,
        user_id=str(raw.get("author") or DELETED_AUTHOR),
        body=raw.get("body") or "",
        created_at=datetime.fromtimestamp(raw["created_utc"], tz=UTC),
        permalink=_reddit_url(raw["permalink"]),
    )
