"""The fixture-backed search provider (plan §9, §2.11).

It is the default, so it carries the same obligation ``FakeLLMProvider``
does: it must be able to simulate failure as well as success, or the §8.1
outage paths would have nothing to exercise them offline.
"""

from __future__ import annotations

import pytest

from tripfinder.domain.ports import WebSearchHit, WebSearchProvider, WebSearchQuery
from tripfinder.search.errors import WebSearchUnavailableError
from tripfinder.search.fake import FakeSearchProvider
from tripfinder.search.fixtures import fixture_hits
from tripfinder.search.reddit_urls import post_id_from_url


def test_satisfies_the_port() -> None:
    assert isinstance(FakeSearchProvider(), WebSearchProvider)


async def test_it_serves_the_default_fixture_hits() -> None:
    hits = await FakeSearchProvider().search(WebSearchQuery(query="anything"))

    assert list(hits) == fixture_hits()


async def test_it_honours_the_requested_limit() -> None:
    hits = await FakeSearchProvider().search(WebSearchQuery(query="anything", limit=2))

    assert len(hits) == 2


async def test_it_records_every_query_it_was_asked() -> None:
    provider = FakeSearchProvider()

    await provider.search(WebSearchQuery(query="first"))
    await provider.search(WebSearchQuery(query="second"))

    assert provider.queries == ["first", "second"]


async def test_supplied_hits_replace_the_fixtures() -> None:
    hit = WebSearchHit(url="https://www.reddit.com/r/travel/comments/abc123/x/")

    hits = await FakeSearchProvider(hits=[hit]).search(WebSearchQuery(query="anything"))

    assert list(hits) == [hit]


async def test_a_configured_failure_is_raised_on_every_call() -> None:
    error = WebSearchUnavailableError(kind="rate_limited", message="HTTP 429", attempts=3)
    provider = FakeSearchProvider(failure=error)

    with pytest.raises(WebSearchUnavailableError):
        await provider.search(WebSearchQuery(query="anything"))


class TestTheFixturesExerciseTheRealDiscardPath:
    """The fixture list is not four identical rows on purpose — the fake has
    to put the same decisions in front of the pipeline the real one will."""

    def test_two_distinct_threads_are_hydratable(self) -> None:
        post_ids = {
            post_id
            for hit in fixture_hits()
            if (post_id := post_id_from_url(hit.url)) is not None
        }

        assert post_ids == {"post1", "post2"}

    def test_at_least_one_fixture_url_names_no_post(self) -> None:
        assert any(post_id_from_url(hit.url) is None for hit in fixture_hits())

    def test_the_hydratable_ids_match_the_fake_source_adapters_fixtures(self) -> None:
        """Otherwise a fake end-to-end run would hydrate nothing and look thin."""
        from tripfinder.sources.fake.fixtures import fixture_documents

        assert {document.id for document in fixture_documents()} == {"post1", "post2"}
