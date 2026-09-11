"""ArcticShiftClient retry/backoff/politeness tests (plan §8, Phase 4 acceptance).

Every test uses ``httpx.MockTransport`` — no network call ever leaves the
process (plan §9).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from tripfinder.sources.arctic_shift.client import ArcticShiftClient
from tripfinder.sources.arctic_shift.config import ArcticShiftConfig
from tripfinder.sources.arctic_shift.errors import (
    ArcticShiftRequestError,
    ArcticShiftUnavailableError,
)

LoadFixture = Callable[[str], dict[str, Any]]
FastConfig = Callable[..., dict[str, Any]]
Handler = Callable[[httpx.Request], httpx.Response]


def _client(
    handler: Handler, fast_config: FastConfig, **config_overrides: Any
) -> ArcticShiftClient:
    config = ArcticShiftConfig(**fast_config(**config_overrides))
    return ArcticShiftClient(config, transport=httpx.MockTransport(handler))


async def test_get_returns_body_on_success(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=load_fixture("posts_ids_batch.json"))

    client = _client(handler, fast_config)

    body = await client.get("/api/posts/search", params={"query": "nature"})

    assert len(body["data"]) == 2
    assert len(calls) == 1


async def test_get_retries_on_429_then_succeeds(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"data": None, "error": "rate limited"})
        return httpx.Response(200, json=load_fixture("posts_ids_batch.json"))

    client = _client(handler, fast_config)

    body = await client.get("/api/posts/search", params={"query": "nature"})

    assert len(calls) == 2
    assert len(body["data"]) == 2


async def test_get_raises_unavailable_after_exhausting_retries_on_429(
    fast_config: FastConfig,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, json={"data": None, "error": "rate limited"})

    client = _client(handler, fast_config, max_retries=2)

    with pytest.raises(ArcticShiftUnavailableError) as excinfo:
        await client.get("/api/posts/search", params={"query": "nature"})

    assert excinfo.value.kind == "rate_limited"
    assert excinfo.value.attempts == 3
    assert len(calls) == 3


async def test_get_raises_request_error_on_400_without_retrying(fast_config: FastConfig) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, json={"data": None, "error": "bad query"})

    client = _client(handler, fast_config)

    with pytest.raises(ArcticShiftRequestError):
        await client.get("/api/posts/search", params={"query": "nature"})

    assert len(calls) == 1


async def test_get_retries_on_soft_error_body_then_succeeds(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=load_fixture("error_soft_timeout.json"))
        return httpx.Response(200, json=load_fixture("posts_ids_batch.json"))

    client = _client(handler, fast_config)

    body = await client.get("/api/posts/search", params={"query": "nature"})

    assert len(calls) == 2
    assert len(body["data"]) == 2


async def test_get_raises_unavailable_on_malformed_json_after_retries(
    fast_config: FastConfig,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"not json{{{")

    client = _client(handler, fast_config, max_retries=1)

    with pytest.raises(ArcticShiftUnavailableError) as excinfo:
        await client.get("/api/posts/search", params={"query": "nature"})

    assert excinfo.value.kind == "malformed"
    assert len(calls) == 2


async def test_get_retries_on_5xx_then_succeeds(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, text="service unavailable")
        return httpx.Response(200, json=load_fixture("posts_ids_batch.json"))

    client = _client(handler, fast_config)

    body = await client.get("/api/posts/search", params={"query": "nature"})

    assert len(calls) == 2
    assert len(body["data"]) == 2


async def test_get_retries_on_network_error_then_succeeds(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=load_fixture("posts_ids_batch.json"))

    client = _client(handler, fast_config)

    body = await client.get("/api/posts/search", params={"query": "nature"})

    assert len(calls) == 2
    assert len(body["data"]) == 2


async def test_throttle_enforces_minimum_interval_between_requests(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("posts_ids_empty.json"))

    config = ArcticShiftConfig(**fast_config(requests_per_second=20.0))
    client = ArcticShiftClient(config, transport=httpx.MockTransport(handler))

    start = time.monotonic()
    await client.get("/api/posts/search", params={"query": "a"})
    await client.get("/api/posts/search", params={"query": "b"})
    elapsed = time.monotonic() - start

    assert elapsed >= 1.0 / 20.0


async def test_health_check_returns_true_on_success(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("posts_ids_batch.json"))

    client = _client(handler, fast_config)

    assert await client.health_check() is True


async def test_health_check_returns_false_on_5xx_without_retrying(fast_config: FastConfig) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, text="down")

    client = _client(handler, fast_config)

    assert await client.health_check() is False
    assert len(calls) == 1


async def test_health_check_returns_false_on_network_error(fast_config: FastConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(handler, fast_config)

    assert await client.health_check() is False


async def test_health_check_returns_false_on_soft_error_body(
    load_fixture: LoadFixture, fast_config: FastConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("error_soft_timeout.json"))

    client = _client(handler, fast_config)

    assert await client.health_check() is False
