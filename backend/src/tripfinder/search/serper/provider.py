"""SerperSearchProvider — real Google results behind the port (plan §2.11).

Serper answers a single ``POST /search`` with the organic result list Google
would show. That is the entire integration: no crawling, no scraping, and no
Reddit content — only the addresses discovery needs.

Retries mirror the Arctic Shift client's policy (exponential backoff, 429 and
5xx retried, other 4xx raised immediately) because §8.1 treats both
dependencies the same way, and "a single 429 is not an outage" applies here
too.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from tripfinder.domain.ports import WebSearchHit, WebSearchQuery
from tripfinder.search.errors import (
    WebSearchCredentialError,
    WebSearchRequestError,
    WebSearchUnavailableError,
)
from tripfinder.search.serper.config import SerperConfig

logger = logging.getLogger(__name__)


class SerperSearchProvider:
    """``WebSearchProvider`` over Serper.dev."""

    name = "serper"

    def __init__(
        self,
        config: SerperConfig | None = None,
        *,
        api_key: SecretStr | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config or SerperConfig()
        self._api_key = api_key
        self._http = httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        # Clamped rather than passed through: above this ceiling Serper
        # rejects a `site:`-scoped query outright, and every discovery query
        # carries one. See ``SerperConfig.max_results_per_query``.
        num = min(query.limit, self._config.max_results_per_query)
        if num < query.limit:
            logger.debug(
                "serper: asking for %d results instead of %d (provider ceiling)",
                num,
                query.limit,
            )
        body = await self._post(
            {
                "q": query.query,
                "num": num,
                "gl": self._config.country,
                "hl": self._config.language,
            }
        )
        return [hit for raw in body.get("organic") or [] if (hit := _to_hit(raw)) is not None]

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._api_key is None:
            # Raised on the call, not at construction: a missing key must
            # surface as a failed research naming its cause (plan §0.1),
            # not as a process that would not start.
            raise WebSearchCredentialError("SERPER_API_KEY is not set")

        headers = {
            "X-API-KEY": self._api_key.get_secret_value(),
            "Content-Type": "application/json",
        }
        last_error: WebSearchUnavailableError | None = None
        attempts = self._config.max_retries + 1

        for attempt in range(attempts):
            if attempt > 0:
                await asyncio.sleep(self._config.backoff_base_seconds * (2 ** (attempt - 1)))

            try:
                response = await self._http.post("/search", json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                last_error = WebSearchUnavailableError(
                    kind="timeout", message=str(exc), attempts=attempt + 1
                )
                continue
            except httpx.TransportError as exc:
                last_error = WebSearchUnavailableError(
                    kind="network", message=str(exc), attempts=attempt + 1
                )
                continue

            if response.status_code in (401, 403):
                raise WebSearchCredentialError(f"serper rejected the API key: {response.text}")
            if response.status_code == 429:
                last_error = WebSearchUnavailableError(
                    kind="rate_limited", message="HTTP 429", attempts=attempt + 1
                )
                continue
            if response.status_code >= 500:
                last_error = WebSearchUnavailableError(
                    kind="http_5xx", message=f"HTTP {response.status_code}", attempts=attempt + 1
                )
                continue
            if response.status_code >= 400:
                raise WebSearchRequestError(f"HTTP {response.status_code}: {response.text}")

            try:
                parsed: dict[str, Any] = response.json()
            except ValueError as exc:
                last_error = WebSearchUnavailableError(
                    kind="malformed", message=f"invalid JSON: {exc}", attempts=attempt + 1
                )
                continue

            return parsed

        assert last_error is not None
        raise last_error


def _to_hit(raw: object) -> WebSearchHit | None:
    """One organic result, or ``None`` if it is not shaped like one.

    A result without a link is not a partial hit, it is no hit — dropping it
    is the only honest reading, and it costs nothing because the provider
    returns many.
    """
    if not isinstance(raw, dict):
        return None
    link = raw.get("link")
    if not isinstance(link, str) or not link:
        logger.warning("serper: dropped result with no link: %r", raw)
        return None
    return WebSearchHit(
        url=link,
        title=str(raw.get("title") or ""),
        snippet=str(raw.get("snippet") or ""),
    )
