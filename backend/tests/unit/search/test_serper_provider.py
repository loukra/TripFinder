"""The Serper adapter (plan §2.11).

Two things under test. The first is ordinary: the provider satisfies
``WebSearchProvider`` and maps Google's organic results to hits. The second
is plan §0.1's — every way this call can go wrong raises with a named cause,
because a provider that degraded quietly would hand discovery an empty
result list, and an empty result list is indistinguishable from a question
nobody discussed.

No test here touches the network: ``httpx.MockTransport`` serves every
response (plan §9).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from tripfinder.domain.ports import WebSearchProvider, WebSearchQuery
from tripfinder.search.errors import (
    WebSearchCredentialError,
    WebSearchRequestError,
    WebSearchUnavailableError,
)
from tripfinder.search.serper import SerperConfig, SerperSearchProvider

Handler = Callable[[httpx.Request], httpx.Response]

API_KEY = SecretStr("serper-not-a-real-key")

ORGANIC_BODY: dict[str, Any] = {
    "organic": [
        {
            "title": "Most underrated state for nature? : r/travel",
            "link": "https://www.reddit.com/r/travel/comments/1wbve58/most_underrated/",
            "snippet": "Alaska is amazing for nature.",
            "position": 1,
        },
        {
            "title": "Hidden gem national parks : r/travel",
            "link": "https://www.reddit.com/r/travel/comments/1wc001a/hidden_gem/",
            "snippet": "Nothing beats it.",
            "position": 2,
        },
    ]
}


def _provider(
    handler: Handler, *, api_key: SecretStr | None = API_KEY, **overrides: Any
) -> SerperSearchProvider:
    config = SerperConfig(backoff_base_seconds=0.001, **overrides)
    return SerperSearchProvider(
        config, api_key=api_key, transport=httpx.MockTransport(handler)
    )


def _ok(body: dict[str, Any]) -> Handler:
    return lambda request: httpx.Response(200, json=body)


def test_satisfies_the_port() -> None:
    assert isinstance(_provider(_ok(ORGANIC_BODY)), WebSearchProvider)


class TestASuccessfulSearch:
    async def test_organic_results_become_hits(self) -> None:
        provider = _provider(_ok(ORGANIC_BODY))

        hits = await provider.search(WebSearchQuery(query="underrated states"))

        assert [hit.url for hit in hits] == [
            "https://www.reddit.com/r/travel/comments/1wbve58/most_underrated/",
            "https://www.reddit.com/r/travel/comments/1wc001a/hidden_gem/",
        ]
        assert hits[0].title.startswith("Most underrated")
        assert hits[0].snippet == "Alaska is amazing for nature."

    async def test_the_query_limit_and_locale_reach_serper(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=ORGANIC_BODY)

        provider = _provider(handler, country="de", language="de", max_results_per_query=25)

        await provider.search(WebSearchQuery(query="underrated states", limit=25))

        payload = json.loads(calls[0].content)
        assert payload == {"q": "underrated states", "num": 25, "gl": "de", "hl": "de"}
        assert calls[0].url.path == "/search"


class TestTheResultCountIsClampedToTheProviderCeiling:
    """Measured against the live free tier: ``site:reddit.com`` with ``num=10``
    succeeds and the same query with ``num=25`` is rejected with HTTP 400.
    Every discovery query carries that operator, so an unclamped request
    would fail every search and take the research down as an outage."""

    async def _num_sent(self, *, limit: int, ceiling: int) -> int:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=ORGANIC_BODY)

        provider = _provider(handler, max_results_per_query=ceiling)
        await provider.search(WebSearchQuery(query="underrated states", limit=limit))

        num: int = json.loads(calls[0].content)["num"]
        return num

    async def test_a_budget_above_the_ceiling_is_clamped_down_to_it(self) -> None:
        assert await self._num_sent(limit=25, ceiling=10) == 10

    async def test_a_budget_below_the_ceiling_is_passed_through_untouched(self) -> None:
        assert await self._num_sent(limit=5, ceiling=10) == 5

    async def test_the_default_ceiling_is_the_free_tiers(self) -> None:
        assert SerperConfig().max_results_per_query == 10

    async def test_the_api_key_travels_in_the_header_and_nowhere_else(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=ORGANIC_BODY)

        await _provider(handler).search(WebSearchQuery(query="underrated states"))

        assert calls[0].headers["X-API-KEY"] == API_KEY.get_secret_value()
        assert API_KEY.get_secret_value() not in str(calls[0].url)
        assert API_KEY.get_secret_value() not in calls[0].content.decode()

    async def test_no_organic_results_is_an_empty_list_not_an_error(self) -> None:
        provider = _provider(_ok({"searchParameters": {"q": "x"}}))

        assert await provider.search(WebSearchQuery(query="nothing")) == []

    async def test_a_result_with_no_link_is_dropped_rather_than_half_built(self) -> None:
        provider = _provider(
            _ok({"organic": [{"title": "no link here"}, ORGANIC_BODY["organic"][0]]})
        )

        hits = await provider.search(WebSearchQuery(query="underrated states"))

        assert [hit.url for hit in hits] == [ORGANIC_BODY["organic"][0]["link"]]

    async def test_a_result_missing_title_and_snippet_still_yields_its_address(self) -> None:
        provider = _provider(_ok({"organic": [{"link": "https://redd.it/1wbve58"}]}))

        (hit,) = await provider.search(WebSearchQuery(query="underrated states"))

        assert hit.url == "https://redd.it/1wbve58"
        assert hit.title == ""


class TestEveryFailureNamesItsCause:
    async def test_a_missing_key_fails_on_the_call_not_at_construction(self) -> None:
        provider = _provider(_ok(ORGANIC_BODY), api_key=None)

        with pytest.raises(WebSearchCredentialError):
            await provider.search(WebSearchQuery(query="underrated states"))

    @pytest.mark.parametrize("status", [401, 403])
    async def test_a_rejected_key_is_a_credential_error_and_is_never_retried(
        self, status: int
    ) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(status, text="forbidden")

        with pytest.raises(WebSearchCredentialError):
            await _provider(handler).search(WebSearchQuery(query="x"))

        assert calls == 1

    async def test_a_4xx_is_our_bug_and_is_never_retried(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(400, text="bad request")

        with pytest.raises(WebSearchRequestError):
            await _provider(handler).search(WebSearchQuery(query="x"))

        assert calls == 1

    async def test_a_429_is_retried_and_then_reported_as_rate_limited(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(429, text="slow down")

        with pytest.raises(WebSearchUnavailableError) as caught:
            await _provider(handler, max_retries=2).search(WebSearchQuery(query="x"))

        assert caught.value.kind == "rate_limited"
        assert calls == 3

    async def test_a_5xx_is_retried_and_then_reported(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="unavailable")

        with pytest.raises(WebSearchUnavailableError) as caught:
            await _provider(handler, max_retries=1).search(WebSearchQuery(query="x"))

        assert caught.value.kind == "http_5xx"

    async def test_a_timeout_is_reported_as_a_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        with pytest.raises(WebSearchUnavailableError) as caught:
            await _provider(handler, max_retries=0).search(WebSearchQuery(query="x"))

        assert caught.value.kind == "timeout"

    async def test_a_transport_failure_is_reported_as_a_network_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        with pytest.raises(WebSearchUnavailableError) as caught:
            await _provider(handler, max_retries=0).search(WebSearchQuery(query="x"))

        assert caught.value.kind == "network"

    async def test_unparseable_json_is_malformed_not_an_empty_result(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>not json</html>")

        with pytest.raises(WebSearchUnavailableError) as caught:
            await _provider(handler, max_retries=0).search(WebSearchQuery(query="x"))

        assert caught.value.kind == "malformed"

    async def test_a_transient_failure_that_then_succeeds_is_not_an_outage(self) -> None:
        """§8.1: "a single 429 is not an outage"."""
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, text="slow down")
            return httpx.Response(200, json=ORGANIC_BODY)

        hits = await _provider(handler, max_retries=2).search(WebSearchQuery(query="x"))

        assert len(hits) == 2

    async def test_the_error_message_never_reveals_the_key(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="internal error")

        with pytest.raises(WebSearchUnavailableError) as caught:
            await _provider(handler, max_retries=0).search(WebSearchQuery(query="x"))

        assert API_KEY.get_secret_value() not in str(caught.value)
