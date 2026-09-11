"""Agent-facing tool boundary over a ``WebSearchProvider`` (plan §2.11, §4.6 step 3).

The discovery agent never calls a provider directly. This is the only thing
it can call: a single bounded ``search`` tool that takes a plain-language
query and returns Reddit *post ids*. Three things happen inside it that the
agent must not be trusted with:

* the query is restricted to Reddit here, not by the model writing
  ``site:reddit.com`` itself — a restriction the agent can forget is not a
  restriction;
* result URLs are resolved to post ids, so an address that names no post
  costs nothing downstream (plan §10 Phase 14.5 acceptance);
* every provider failure becomes a structured result instead of a raised
  exception, carrying its §8.1 ``failure_kinds`` label so a dead search
  engine still reaches health accounting rather than looking like a query
  with no answers.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel, Field

from tripfinder.domain.ports import WebSearchHit, WebSearchProvider, WebSearchQuery
from tripfinder.search.reddit_urls import post_id_from_url
from tripfinder.sources.failures import failure_kind

logger = logging.getLogger(__name__)

SITE_RESTRICTION = "site:reddit.com"


class ThreadSearchResult(BaseModel):
    """What the discovery agent sees back from one ``search`` tool call."""

    query: str
    post_ids: list[str] = Field(default_factory=list)
    hits_seen: int = 0
    """How many results the provider returned, before any were discarded.

    Plan §0.1: the gap between this and ``len(post_ids)`` is the number of
    addresses we chose not to follow, and it has to be visible rather than
    inferred from an unexpectedly short list."""
    error: str | None = None
    failure_kind: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class RedditThreadSearchTool:
    """The bounded, failure-safe ``search`` tool handed to the discovery agent."""

    def __init__(self, provider: WebSearchProvider, *, limit_per_query: int) -> None:
        self._provider = provider
        self._limit_per_query = limit_per_query

    async def search(self, query: str) -> ThreadSearchResult:
        restricted = f"{query} {SITE_RESTRICTION}"
        try:
            hits: Sequence[WebSearchHit] = await self._provider.search(
                WebSearchQuery(query=restricted, limit=self._limit_per_query)
            )
        except Exception as exc:  # a provider failure must never crash discovery
            logger.warning("search tool: query %r failed: %s", query, exc)
            return ThreadSearchResult(
                query=query, error=str(exc), failure_kind=failure_kind(exc)
            )

        post_ids: list[str] = []
        for hit in hits:
            post_id = post_id_from_url(hit.url)
            if post_id is not None and post_id not in post_ids:
                post_ids.append(post_id)
        return ThreadSearchResult(query=query, post_ids=post_ids, hits_seen=len(hits))
