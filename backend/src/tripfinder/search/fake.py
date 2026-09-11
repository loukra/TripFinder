"""Fixture-backed ``WebSearchProvider`` for tests and the fake pipeline (plan §9).

Zero network calls, and the **default** provider — plan §2.11 requires
``SEARCH_PROVIDER`` to be set explicitly before anything reaches Serper, so
no test run and no accidental start-up can spend a query quota.

Like ``FakeLLMProvider`` it can simulate failure as well as success: pass
``failure`` to make every call raise. A fake that could only succeed would
let the §8.1 outage paths go untested, and those are the paths §0.1 cares
about most.
"""

from __future__ import annotations

from collections.abc import Sequence

from tripfinder.domain.ports import WebSearchHit, WebSearchQuery
from tripfinder.search.errors import WebSearchError
from tripfinder.search.fixtures import fixture_hits


class FakeSearchProvider:
    """Serves web search hits from an in-memory fixture."""

    name = "fake"

    def __init__(
        self,
        *,
        hits: Sequence[WebSearchHit] | None = None,
        failure: WebSearchError | None = None,
    ) -> None:
        self._hits = list(fixture_hits() if hits is None else hits)
        self._failure = failure
        self.queries: list[str] = []
        """Every query this provider was asked, in order — for assertions."""

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        self.queries.append(query.query)
        if self._failure is not None:
            raise self._failure
        return self._hits[: query.limit]
