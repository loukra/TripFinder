"""ArcticShiftAdapter — the MVP's only real ``SourceAdapter`` (plan §1, §8).

Endpoint choices:

* ``search`` uses ``/api/posts/search`` — it returns thread-level results
  directly as ``SourceDocument``s, matching the port's return type.
* ``fetch_comments`` uses ``/api/comments/search`` rather than
  ``/api/comments/tree``: both return the same comment records, but the
  flat search endpoint shares its ``after``/``before`` date-cursor pagination
  with ``posts/search`` and each record still carries ``link_id``/``parent_id``
  for threading — the tree endpoint's nested ``kind``/``data``/``more``
  structure isn't needed to satisfy this port.

Both list endpoints paginate on ``created_utc`` since Arctic Shift has no
cursor token: each page's oldest/newest timestamp becomes the next page's
``before``/``after``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from tripfinder.domain.models import Comment, SourceDocument
from tripfinder.domain.ports import SourceSearchQuery
from tripfinder.sources.arctic_shift.client import ArcticShiftClient
from tripfinder.sources.arctic_shift.config import ArcticShiftConfig
from tripfinder.sources.arctic_shift.mapping import (
    comment_to_domain,
    is_bot_author,
    post_to_document,
)

logger = logging.getLogger(__name__)


class ArcticShiftAdapter:
    """Real ``SourceAdapter`` over the Arctic Shift Reddit archive."""

    name = "arctic_shift"

    def __init__(
        self,
        config: ArcticShiftConfig | None = None,
        *,
        client: ArcticShiftClient | None = None,
    ) -> None:
        self._config = config or ArcticShiftConfig()
        self._client = client or ArcticShiftClient(self._config)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health_check(self) -> bool:
        return await self._client.health_check()

    def _map_post(self, raw: dict[str, Any]) -> SourceDocument | None:
        try:
            return post_to_document(raw, source=self.name)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("arctic_shift: dropped malformed post %r: %s", raw.get("id"), exc)
            return None

    def _map_comment(self, raw: dict[str, Any], *, document_id: str) -> Comment | None:
        try:
            return comment_to_domain(raw, source_document_id=document_id)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("arctic_shift: dropped malformed comment %r: %s", raw.get("id"), exc)
            return None

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        documents: list[SourceDocument] = []
        before: int | None = None

        while len(documents) < query.limit:
            page_limit = min(self._config.page_size, query.limit - len(documents))
            params = {"query": query.query, "limit": str(page_limit), "sort": "desc"}
            # The live API rejects a bare `query` with no author/subreddit
            # scope (plan §8) — `SourceSearchQuery.subreddit` is how the
            # caller supplies it (see analysis/discovery.py).
            if query.subreddit:
                params["subreddit"] = query.subreddit
            if before is not None:
                params["before"] = str(before)

            body = await self._client.get("/api/posts/search", params=params)
            raw_items = body.get("data") or []
            if not raw_items:
                break

            for raw in raw_items:
                document = self._map_post(raw)
                if document is not None:
                    documents.append(document)

            before = raw_items[-1]["created_utc"]
            if len(raw_items) < page_limit:
                break

        return documents[: query.limit]

    async def fetch_document(self, document_id: str) -> SourceDocument:
        body = await self._client.get("/api/posts/ids", params={"ids": document_id})
        for raw in body.get("data") or []:
            document = self._map_post(raw)
            if document is not None:
                return document
        raise LookupError(f"ArcticShiftAdapter has no document {document_id!r}")

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        comments: list[Comment] = []
        after: int | None = None
        link_id = f"t3_{document.id}"

        while True:
            params = {"link_id": link_id, "limit": str(self._config.page_size), "sort": "asc"}
            if after is not None:
                params["after"] = str(after)

            body = await self._client.get("/api/comments/search", params=params)
            raw_items = body.get("data") or []
            if not raw_items:
                break

            for raw in raw_items:
                author = str(raw.get("author") or "[deleted]")
                if is_bot_author(author, denylist=self._config.bot_denylist):
                    continue
                comment = self._map_comment(raw, document_id=document.id)
                if comment is not None:
                    comments.append(comment)

            after = raw_items[-1]["created_utc"] + 1
            if len(raw_items) < self._config.page_size:
                break

        return comments
