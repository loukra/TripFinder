"""Low-level HTTP access to Arctic Shift: retries, backoff, politeness, health.

Adapter responsibilities per plan §8: exponential backoff, 429 handling,
response validation. Kept separate from ``adapter.py`` so retry/rate-limit
policy has nothing to do with domain mapping.

Arctic Shift also signals its rate limit as a plain ``422`` with body
``{"data": null, "error": "Timeout. Maybe slow down a bit"}`` rather than a
``429`` — indistinguishable from a genuine bad-request 422 by status code
alone, so it is detected by that body and retried with backoff exactly like
a 429 instead of being raised immediately as a non-retryable request error.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from tripfinder.sources.arctic_shift.config import ArcticShiftConfig
from tripfinder.sources.arctic_shift.errors import (
    ArcticShiftRequestError,
    ArcticShiftUnavailableError,
)

_SLOW_DOWN_MARKER = "slow down"


def _is_rate_limited(response: httpx.Response) -> bool:
    """True for a 429, or Arctic Shift's own 422-shaped "slow down" signal."""
    if response.status_code == 429:
        return True
    if response.status_code != 422:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return _SLOW_DOWN_MARKER in str(body.get("error", "")).lower()


class ArcticShiftClient:
    """Wraps ``httpx.AsyncClient`` with retry/backoff and a request-rate ceiling."""

    def __init__(
        self,
        config: ArcticShiftConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            headers={"User-Agent": config.user_agent},
            transport=transport,
        )
        self._min_interval = 1.0 / config.requests_per_second
        self._last_request_at: float | None = None
        self._throttle_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        """GET ``path``, retrying transient failures with exponential backoff.

        Raises ``ArcticShiftRequestError`` immediately for a non-retryable
        4xx, or ``ArcticShiftUnavailableError`` once retries are exhausted.
        """
        last_error: ArcticShiftUnavailableError | None = None
        attempts = self._config.max_retries + 1

        for attempt in range(attempts):
            if attempt > 0:
                await asyncio.sleep(self._config.backoff_base_seconds * (2 ** (attempt - 1)))
            await self._throttle()

            try:
                response = await self._http.get(path, params=params)
            except httpx.TransportError as exc:
                last_error = ArcticShiftUnavailableError(
                    kind="network", message=str(exc), attempts=attempt + 1
                )
                continue

            if _is_rate_limited(response):
                last_error = ArcticShiftUnavailableError(
                    kind="rate_limited",
                    message=f"HTTP {response.status_code}: {response.text}",
                    attempts=attempt + 1,
                )
                continue
            if response.status_code >= 500:
                last_error = ArcticShiftUnavailableError(
                    kind="http_5xx", message=f"HTTP {response.status_code}", attempts=attempt + 1
                )
                continue
            if response.status_code >= 400:
                raise ArcticShiftRequestError(f"HTTP {response.status_code}: {response.text}")

            try:
                body: dict[str, Any] = response.json()
            except ValueError as exc:
                last_error = ArcticShiftUnavailableError(
                    kind="malformed", message=f"invalid JSON: {exc}", attempts=attempt + 1
                )
                continue

            if body.get("data") is None and "error" in body:
                last_error = ArcticShiftUnavailableError(
                    kind="malformed", message=str(body["error"]), attempts=attempt + 1
                )
                continue

            return body

        assert last_error is not None
        raise last_error

    async def health_check(self) -> bool:
        """A single fast, unretried probe — preflight must fail fast (plan §8.1)."""
        try:
            response = await self._http.get(
                "/api/posts/search",
                params={"limit": "1"},
                timeout=self._config.health_check_timeout_seconds,
            )
        except httpx.TransportError:
            return False
        if response.status_code != 200:
            return False
        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            return False
        return body.get("data") is not None

    async def _throttle(self) -> None:
        async with self._throttle_lock:
            now = time.monotonic()
            if self._last_request_at is not None:
                wait = self._min_interval - (now - self._last_request_at)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()
