"""ArcticShiftAdapter tests against cassette fixtures (plan §8, Phase 4 acceptance).

Covers: success, empty results, pagination, deleted authors, bot filtering,
malformed-item skipping, and retry-exhaustion propagation. All offline via
``httpx.MockTransport`` (plan §9 — tests never touch the network).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import HttpUrl

from tripfinder.domain.models import SourceDocument
from tripfinder.domain.ports import SourceAdapter, SourceSearchQuery
from tripfinder.sources.arctic_shift.adapter import ArcticShiftAdapter
from tripfinder.sources.arctic_shift.client import ArcticShiftClient
from tripfinder.sources.arctic_shift.config import ArcticShiftConfig
from tripfinder.sources.arctic_shift.errors import ArcticShiftUnavailableError

LoadFixture = Callable[[str], dict[str, Any]]
FastConfig = Callable[..., dict[str, Any]]
Handler = Callable[[httpx.Request], httpx.Response]


def _adapter(
    handler: Handler, fast_config: FastConfig, **config_overrides: Any
) -> ArcticShiftAdapter:
    config = ArcticShiftConfig(**fast_config(**config_overrides))
    client = ArcticShiftClient(config, transport=httpx.MockTransport(handler))
    return ArcticShiftAdapter(config, client=client)


def _source_document(load_fixture: LoadFixture) -> SourceDocument:
    raw = load_fixture("posts_search_success.json")["data"][0]
    return SourceDocument(
        id=raw["id"],
        source="arctic_shift",
        title=raw["title"],
        url=HttpUrl("https://www.reddit.com/r/travel/comments/1wbve58/x/"),
        subreddit=raw["subreddit"],
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
        comment_count=raw["num_comments"],
    )


def test_satisfies_source_adapter_protocol(fast_config: FastConfig) -> None:
    adapter = _adapter(lambda request: httpx.Response(200), fast_config)
    assert isinstance(adapter, SourceAdapter)


async def test_search_maps_fixture_posts_to_documents(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("posts_search_success.json"))

    adapter = _adapter(handler, fast_config)

    documents = await adapter.search(SourceSearchQuery(query="underrated nature"))

    assert [d.id for d in documents] == ["1wbve58", "1wc001a"]
    assert all(d.source == "arctic_shift" for d in documents)


async def test_search_sends_subreddit_when_given(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    """The live search API rejects a bare `query` with no author/subreddit/
    link_id/parent_id to scope it (plan §8) — this is the request-shape
    half of that contract, cassette tests alone can't catch since the
    handler never has to look at what it was sent."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=load_fixture("posts_search_success.json"))

    adapter = _adapter(handler, fast_config)

    await adapter.search(SourceSearchQuery(query="underrated nature", subreddit="travel"))

    assert calls[0].url.params["subreddit"] == "travel"


async def test_search_omits_subreddit_param_when_not_given(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=load_fixture("posts_search_success.json"))

    adapter = _adapter(handler, fast_config)

    await adapter.search(SourceSearchQuery(query="underrated nature"))

    assert "subreddit" not in calls[0].url.params


async def test_search_returns_empty_sequence_for_empty_results(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=load_fixture("posts_search_empty.json"))

    adapter = _adapter(handler, fast_config)

    documents = await adapter.search(SourceSearchQuery(query="nothing matches this"))

    assert documents == []
    assert len(calls) == 1


async def test_search_paginates_across_pages_until_limit_reached(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "before" in request.url.params:
            return httpx.Response(200, json=load_fixture("posts_search_page2.json"))
        return httpx.Response(200, json=load_fixture("posts_search_success.json"))

    adapter = _adapter(handler, fast_config, page_size=2)

    documents = await adapter.search(SourceSearchQuery(query="underrated", limit=3))

    assert [d.id for d in documents] == ["1wbve58", "1wc001a", "1wc002b"]


async def test_search_drops_malformed_item_and_keeps_valid_one(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("posts_search_malformed_item.json"))

    adapter = _adapter(handler, fast_config)

    documents = await adapter.search(SourceSearchQuery(query="underrated", limit=1))

    assert [d.id for d in documents] == ["1wbve58"]


async def test_search_propagates_error_once_retries_are_exhausted(fast_config: FastConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"data": None, "error": "rate limited"})

    adapter = _adapter(handler, fast_config, max_retries=1)

    with pytest.raises(ArcticShiftUnavailableError):
        await adapter.search(SourceSearchQuery(query="underrated"))


async def test_fetch_document_returns_matching_document(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("posts_ids_success.json"))

    adapter = _adapter(handler, fast_config)

    document = await adapter.fetch_document("1wc001a")

    assert document.title == "Hidden gem national parks"


async def test_fetch_document_raises_lookup_error_when_not_found(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("posts_ids_empty.json"))

    adapter = _adapter(handler, fast_config)

    with pytest.raises(LookupError):
        await adapter.fetch_document("does-not-exist")


async def test_fetch_comments_filters_bots_keeps_deleted_authors_and_paginates(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "after" in request.url.params:
            return httpx.Response(200, json=load_fixture("comments_search_page2.json"))
        return httpx.Response(200, json=load_fixture("comments_search_success.json"))

    adapter = _adapter(handler, fast_config, page_size=4)

    comments = await adapter.fetch_comments(_source_document(load_fixture))

    assert [c.id for c in comments] == ["p8t0od8", "p8t0oe9", "p8t0og1"]
    assert comments[1].user_id == "[deleted]"


async def test_fetch_comments_returns_empty_for_no_comments(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("comments_search_empty.json"))

    adapter = _adapter(handler, fast_config)

    comments = await adapter.fetch_comments(_source_document(load_fixture))

    assert comments == []


async def test_health_check_delegates_to_client(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("posts_search_success.json"))

    adapter = _adapter(handler, fast_config)

    assert await adapter.health_check() is True
