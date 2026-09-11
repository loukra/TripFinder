"""ArcticShiftAdapter tests against cassette fixtures (plan §8, Phase 4 acceptance).

Covers: success, empty results, batching, deleted authors, bot filtering,
malformed-item skipping, and retry-exhaustion propagation. All offline via
``httpx.MockTransport`` (plan §9 — tests never touch the network).

There are no search tests here any more: plan §2.11 removed ``search`` from
the port, because the endpoint behind it measured 1/5 successes against 6/6
for the two endpoints exercised below.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import HttpUrl

from tripfinder.domain.models import SourceDocument
from tripfinder.domain.ports import SourceAdapter
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
    raw = load_fixture("posts_ids_batch.json")["data"][0]
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


async def test_fetch_documents_maps_fixture_posts_to_documents(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("posts_ids_batch.json"))

    adapter = _adapter(handler, fast_config)

    documents = await adapter.fetch_documents(["1wbve58", "1wc001a"])

    assert [d.id for d in documents] == ["1wbve58", "1wc001a"]
    assert all(d.source == "arctic_shift" for d in documents)


async def test_fetch_documents_sends_every_id_in_one_comma_separated_request(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    """The request-shape half of the contract, which a cassette alone cannot
    catch: ``/api/posts/ids`` takes the whole batch in one ``ids`` param."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=load_fixture("posts_ids_batch.json"))

    adapter = _adapter(handler, fast_config)

    await adapter.fetch_documents(["1wbve58", "1wc001a"])

    assert len(calls) == 1
    assert calls[0].url.params["ids"] == "1wbve58,1wc001a"


async def test_fetch_documents_splits_requests_at_the_id_ceiling(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    """Plan §8: Arctic Shift takes at most 500 ids per call, so 501 is two
    calls — and the ceiling is config, so the test can prove the split
    without building a 501-element fixture."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=load_fixture("posts_ids_empty.json"))

    adapter = _adapter(handler, fast_config, max_ids_per_request=2)

    await adapter.fetch_documents(["a", "b", "c", "d", "e"])

    assert [call.url.params["ids"] for call in calls] == ["a,b", "c,d", "e"]


async def test_fetch_documents_makes_no_call_for_an_empty_request(
    fast_config: FastConfig,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"data": []})

    adapter = _adapter(handler, fast_config)

    assert await adapter.fetch_documents([]) == []
    assert calls == []


async def test_fetch_documents_returns_empty_when_the_archive_knows_no_id(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("posts_ids_empty.json"))

    adapter = _adapter(handler, fast_config)

    assert await adapter.fetch_documents(["does-not-exist"]) == []


async def test_fetch_documents_drops_malformed_item_and_keeps_valid_one(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("posts_ids_malformed_item.json"))

    adapter = _adapter(handler, fast_config)

    documents = await adapter.fetch_documents(["1wbve58", "1wc003c"])

    assert [d.id for d in documents] == ["1wbve58"]


async def test_fetch_documents_propagates_error_once_retries_are_exhausted(
    fast_config: FastConfig,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"data": None, "error": "rate limited"})

    adapter = _adapter(handler, fast_config, max_retries=1)

    with pytest.raises(ArcticShiftUnavailableError):
        await adapter.fetch_documents(["1wbve58"])


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
        return httpx.Response(200, json=load_fixture("posts_ids_batch.json"))

    adapter = _adapter(handler, fast_config)

    assert await adapter.health_check() is True
