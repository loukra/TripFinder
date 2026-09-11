"""Search provider selection (plan §2.11, §9).

The load-bearing assertion is the first one: the default is ``fake``, so a
test run or a CI job can never spend a query quota by accident.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from tripfinder.domain.ports import WebSearchProvider
from tripfinder.search.factory import (
    DEFAULT_SEARCH_PROVIDER,
    SearchProviderName,
    build_search_provider,
)
from tripfinder.search.fake import FakeSearchProvider
from tripfinder.search.serper import SerperConfig, SerperSearchProvider


def test_the_default_provider_is_fake() -> None:
    assert DEFAULT_SEARCH_PROVIDER is SearchProviderName.FAKE
    assert isinstance(build_search_provider(), FakeSearchProvider)


def test_fake_is_selected_explicitly_too() -> None:
    assert isinstance(build_search_provider(SearchProviderName.FAKE), FakeSearchProvider)


def test_serper_is_selected_only_when_asked_for() -> None:
    provider = build_search_provider(
        SearchProviderName.SERPER, serper_api_key=SecretStr("serper-test")
    )

    assert isinstance(provider, SerperSearchProvider)


def test_serper_config_is_passed_through() -> None:
    config = SerperConfig(country="de", language="de")

    provider = build_search_provider(
        SearchProviderName.SERPER, serper_api_key=SecretStr("serper-test"), serper_config=config
    )

    assert isinstance(provider, SerperSearchProvider)


@pytest.mark.parametrize("name", list(SearchProviderName))
def test_every_selectable_provider_satisfies_the_port(name: SearchProviderName) -> None:
    provider = build_search_provider(name, serper_api_key=SecretStr("serper-test"))

    assert isinstance(provider, WebSearchProvider)


def test_a_missing_key_is_not_rejected_at_construction() -> None:
    """Same reasoning as ``build_llm_provider``: a missing credential fails
    the *research*, with a reason, rather than the process."""
    provider = build_search_provider(SearchProviderName.SERPER, serper_api_key=None)

    assert isinstance(provider, SerperSearchProvider)
