"""Offline stubs for the OpenAI provider (plan §9: no network in the normal suite).

The client is stubbed at the transport, not at the SDK surface, so every
test still exercises the real request building, the real strict-schema
conversion, and the real status-code-to-exception mapping. A stub that
replaced ``responses.parse`` outright would prove only that our own mock
behaves the way we wrote it.

Exposed as fixtures rather than plain imports, for the reason the Arctic
Shift conftest gives: this test tree has no ``__init__.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI

from tripfinder.ai.openai import OpenAIConfig, OpenAIProvider

Handler = Callable[[httpx2.Request], httpx2.Response]

STUB_API_KEY = "test-key-not-a-real-credential"


@pytest.fixture
def fast_config() -> Callable[..., OpenAIConfig]:
    """Retries off by default, so a failure test asserts one call rather than four."""

    def _fast_config(**overrides: Any) -> OpenAIConfig:
        defaults: dict[str, Any] = {"max_retries": 0, "timeout_seconds": 5.0}
        defaults.update(overrides)
        return OpenAIConfig(**defaults)

    return _fast_config


@pytest.fixture
def provider_for() -> Callable[..., OpenAIProvider]:
    """A provider whose HTTP calls are served by ``handler``, never by the network."""

    def _provider_for(handler: Handler, *, config: OpenAIConfig | None = None) -> OpenAIProvider:
        settings = config or OpenAIConfig()
        client = AsyncOpenAI(
            api_key=STUB_API_KEY,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        )
        return OpenAIProvider(settings, client=client)

    return _provider_for


@pytest.fixture
def json_handler() -> Callable[..., Handler]:
    """A handler returning a fixed status and body, recording every request it saw."""

    def _json_handler(
        status_code: int, body: dict[str, Any], *, seen: list[httpx2.Request] | None = None
    ) -> Handler:
        def handler(request: httpx2.Request) -> httpx2.Response:
            if seen is not None:
                seen.append(request)
            return httpx2.Response(status_code, json=body)

        return handler

    return _json_handler


@pytest.fixture
def raising_handler() -> Callable[[Exception], Handler]:
    """A handler that fails at the transport, the way a real outage does."""

    def _raising_handler(error: Exception) -> Handler:
        def handler(_: httpx2.Request) -> httpx2.Response:
            raise error

        return handler

    return _raising_handler
