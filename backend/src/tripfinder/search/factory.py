"""Search provider selection (plan §2.11, §9).

The mirror of ``ai/factory.py``: ``FakeSearchProvider`` is the default and
``SEARCH_PROVIDER`` must be set explicitly before anything reaches Serper, so
no test run can spend a query quota by accident.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import SecretStr

from tripfinder.domain.ports import WebSearchProvider
from tripfinder.search.fake import FakeSearchProvider
from tripfinder.search.serper import SerperConfig, SerperSearchProvider


class SearchProviderName(StrEnum):
    """The implementations ``SEARCH_PROVIDER`` can select."""

    FAKE = "fake"
    SERPER = "serper"


DEFAULT_SEARCH_PROVIDER = SearchProviderName.FAKE


def build_search_provider(
    provider: SearchProviderName = DEFAULT_SEARCH_PROVIDER,
    *,
    serper_api_key: SecretStr | None = None,
    serper_config: SerperConfig | None = None,
) -> WebSearchProvider:
    """The search provider this process should use.

    A missing key is not rejected here, for the same reason
    ``build_llm_provider`` does not reject one: the failure belongs to a
    research run, where it can be named (plan §0.1), not to process start-up.
    """
    if provider is SearchProviderName.FAKE:
        return FakeSearchProvider()
    return SerperSearchProvider(serper_config, api_key=serper_api_key)
