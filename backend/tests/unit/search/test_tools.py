"""The discovery agent's tool boundary (plan §2.11, §4.6 step 3).

Three properties, each one a thing the agent must not be trusted with: the
Reddit restriction is applied here, addresses are resolved here, and a
provider failure becomes data here rather than an exception.
"""

from __future__ import annotations

from collections.abc import Sequence

from tripfinder.domain.ports import WebSearchHit, WebSearchQuery
from tripfinder.search.errors import WebSearchUnavailableError
from tripfinder.search.tools import SITE_RESTRICTION, RedditThreadSearchTool

THREAD_URL = "https://www.reddit.com/r/travel/comments/{post_id}/a_title/"


def _hit(post_id: str) -> WebSearchHit:
    return WebSearchHit(url=THREAD_URL.format(post_id=post_id))


class _RecordingProvider:
    name = "recording"

    def __init__(self, hits: Sequence[WebSearchHit] = ()) -> None:
        self._hits = list(hits)
        self.queries: list[WebSearchQuery] = []

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        self.queries.append(query)
        return self._hits


class _FailingProvider:
    name = "failing"

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        raise self._error


def _tool(provider: object, *, limit: int = 10) -> RedditThreadSearchTool:
    return RedditThreadSearchTool(provider, limit_per_query=limit)  # type: ignore[arg-type]


async def test_the_query_is_restricted_to_reddit_by_the_tool() -> None:
    provider = _RecordingProvider()

    await _tool(provider).search("underrated states for nature")

    assert provider.queries[0].query == f"underrated states for nature {SITE_RESTRICTION}"


async def test_the_per_query_limit_reaches_the_provider() -> None:
    provider = _RecordingProvider()

    await _tool(provider, limit=25).search("underrated states")

    assert provider.queries[0].limit == 25


async def test_result_urls_become_post_ids() -> None:
    provider = _RecordingProvider([_hit("1wbve58"), _hit("1wc001a")])

    result = await _tool(provider).search("underrated states")

    assert result.ok
    assert result.post_ids == ["1wbve58", "1wc001a"]


async def test_an_address_that_names_no_post_is_dropped_but_still_counted() -> None:
    """Plan §0.1: the gap between ``hits_seen`` and ``post_ids`` is visible,
    not something a caller has to infer from a short list."""
    provider = _RecordingProvider(
        [
            _hit("1wbve58"),
            WebSearchHit(url="https://www.reddit.com/r/travel/"),
            WebSearchHit(url="https://example.com/best-states"),
        ]
    )

    result = await _tool(provider).search("underrated states")

    assert result.post_ids == ["1wbve58"]
    assert result.hits_seen == 3


async def test_the_same_thread_listed_twice_yields_one_id() -> None:
    provider = _RecordingProvider([_hit("1wbve58"), _hit("1wbve58")])

    result = await _tool(provider).search("underrated states")

    assert result.post_ids == ["1wbve58"]


async def test_no_results_is_an_empty_success_not_a_failure() -> None:
    result = await _tool(_RecordingProvider()).search("nothing matches this")

    assert result.ok
    assert result.post_ids == []
    assert result.hits_seen == 0


class TestAProviderFailureBecomesData:
    async def test_it_does_not_propagate(self) -> None:
        provider = _FailingProvider(TimeoutError("no response"))

        result = await _tool(provider).search("underrated states")

        assert not result.ok
        assert result.post_ids == []

    async def test_a_typed_failure_keeps_its_section_8_1_kind(self) -> None:
        error = WebSearchUnavailableError(kind="rate_limited", message="HTTP 429", attempts=3)
        provider = _FailingProvider(error)

        result = await _tool(provider).search("underrated states")

        assert result.failure_kind == "rate_limited"

    async def test_an_untyped_failure_is_still_a_failure(self) -> None:
        """Unknown is not "fine" — it still counts against source health."""
        provider = _FailingProvider(RuntimeError("something odd"))

        result = await _tool(provider).search("underrated states")

        assert not result.ok
        assert result.failure_kind == "unknown"

    async def test_the_failing_query_is_named_on_the_result(self) -> None:
        provider = _FailingProvider(TimeoutError("no response"))

        result = await _tool(provider).search("underrated states")

        assert result.query == "underrated states"
