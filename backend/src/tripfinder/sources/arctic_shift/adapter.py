"""ArcticShiftAdapter — the MVP's only real ``SourceAdapter`` (plan §1, §8).

**Retrieval only** since plan §2.11. This adapter no longer searches: its
keyword endpoint measured 1/5 successes at 5.5–11 s while the two endpoints
used here measured 6/6 at 0.2–1.0 s, so discovery moved to a
``WebSearchProvider`` and Arctic Shift keeps the half it is good at.

Endpoint choices:

* ``fetch_documents`` uses ``/api/posts/ids``, which takes up to 500 ids in
  one request — the discovery step produces ids in bulk, so hydration is one
  or two calls rather than one per thread.
* ``fetch_comments`` uses ``/api/comments/search`` rather than
  ``/api/comments/tree``: both return the same comment records, but the
  flat endpoint paginates on an ``after`` date cursor and each record still
  carries ``link_id``/``parent_id`` for threading — the tree endpoint's
  nested ``kind``/``data``/``more`` structure isn't needed to satisfy this
  port.

``fetch_comments`` paginates on ``created_utc`` since Arctic Shift has no
cursor token: each page's newest timestamp becomes the next page's ``after``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from tripfinder.domain.models import Comment, SourceDocument
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

    async def fetch_documents(self, document_ids: Sequence[str]) -> Sequence[SourceDocument]:
        """Hydrate posts by id, in batches of at most ``max_ids_per_request``.

        Ids the archive does not know are simply absent from the response.
        That is not silently dropped evidence: the caller asked by id, knows
        what it asked for, and can see the shortfall by comparing lengths —
        which is exactly what the discovery step records (plan §0.1).
        """
        documents: list[SourceDocument] = []
        batch_size = self._config.max_ids_per_request

        for start in range(0, len(document_ids), batch_size):
            batch = document_ids[start : start + batch_size]
            body = await self._client.get("/api/posts/ids", params={"ids": ",".join(batch)})
            for raw in body.get("data") or []:
                document = self._map_post(raw)
                if document is not None:
                    documents.append(document)

        return documents

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
