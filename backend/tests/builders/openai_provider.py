"""An OpenAI provider stubbed at the transport (plan §9: no network in the normal suite).

Stubbed at the transport rather than at the SDK surface, so a test still
exercises the real request building, the real strict-schema conversion, and
the real status-code-to-exception mapping. A stub that replaced
``responses.parse`` outright would prove only that our own mock behaves the
way we wrote it.

A builder package rather than a conftest, because two test trees need the
same stub — the provider's own tests and the pipeline's failure tests — and
the test tree has no ``__init__.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx2
from openai import AsyncOpenAI

from tripfinder.ai.openai import OpenAIConfig, OpenAIProvider

Handler = Callable[[httpx2.Request], httpx2.Response]

STUB_API_KEY = "test-key-not-a-real-credential"


def fast_config(**overrides: Any) -> OpenAIConfig:
    """Retries off by default, so a failure test asserts one call rather than four."""
    defaults: dict[str, Any] = {"max_retries": 0, "timeout_seconds": 5.0}
    defaults.update(overrides)
    return OpenAIConfig(**defaults)


def stubbed_provider(handler: Handler, *, config: OpenAIConfig | None = None) -> OpenAIProvider:
    """A provider whose HTTP calls are served by ``handler``, never by the network."""
    settings = config or OpenAIConfig()
    client = AsyncOpenAI(
        api_key=STUB_API_KEY,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return OpenAIProvider(settings, client=client)


def json_handler(
    status_code: int, body: dict[str, Any], *, seen: list[httpx2.Request] | None = None
) -> Handler:
    """A handler returning a fixed status and body, recording every request it saw."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        return httpx2.Response(status_code, json=body)

    return handler


def raising_handler(error: Exception) -> Handler:
    """A handler that fails at the transport, the way a real outage does."""

    def handler(_: httpx2.Request) -> httpx2.Response:
        raise error

    return handler
