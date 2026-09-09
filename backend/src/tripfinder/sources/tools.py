"""Agent-facing tool boundary over a ``SourceAdapter`` (plan §3.1, §4.6 step 3).

The discovery agent never calls a ``SourceAdapter`` directly. This is the
only thing it can call: a single bounded ``search`` tool. It takes and
returns nothing but a query string and domain documents — no adapter
config, retry policy, or credentials ever cross this boundary — and it
turns every adapter failure into a structured result instead of a raised
exception, so one bad query cannot take down the whole discovery loop.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel, Field

from tripfinder.domain.models import SourceDocument
from tripfinder.domain.ports import SourceAdapter, SourceSearchQuery

logger = logging.getLogger(__name__)


class SourceSearchResult(BaseModel):
    """What the discovery agent sees back from one ``search`` tool call."""

    query: str
    documents: list[SourceDocument] = Field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class SourceSearchTool:
    """The bounded, failure-safe ``search`` tool handed to the discovery agent."""

    def __init__(self, adapter: SourceAdapter, *, limit_per_query: int) -> None:
        self._adapter = adapter
        self._limit_per_query = limit_per_query

    async def search(self, query: str) -> SourceSearchResult:
        try:
            documents: Sequence[SourceDocument] = await self._adapter.search(
                SourceSearchQuery(query=query, limit=self._limit_per_query)
            )
        except Exception as exc:  # an adapter failure must never crash the discovery loop
            logger.warning("source tool: search %r failed: %s", query, exc)
            return SourceSearchResult(query=query, error=str(exc))
        return SourceSearchResult(query=query, documents=list(documents))
