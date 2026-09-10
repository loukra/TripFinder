"""Entity alias lookup for triage's deterministic pre-checks (plan §4.5, §4.7).

Plan §4.5 classifies a document cheapest-test-first, and its two cheapest
tests both ask the same question: *does this title name an entity at the
target granularity?* A leading title that names one is `topical`; an
interrogative title that names none is `polling`.

§4.5 says that question is answered by "the same alias table as §9's entity
resolution" — which Phase 9 owns. Triage needs the lookup one phase earlier,
so the interface lands here and Phase 9 supplies the populated table behind
it.

**Erring direction while the table is thin.** An empty table cannot
distinguish "names no entity" from "we have no aliases for this tier", and
guessing wrong the optimistic way promotes a leading thread to `polling` —
the exact corruption plan §4.7 forbids. So a caller must check
``covers(granularity)`` before trusting a negative answer, and fall through
to AI classification when it is false.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Protocol, runtime_checkable

from tripfinder.domain.models import EntityType


@runtime_checkable
class AliasTable(Protocol):
    """Names known at a given entity tier."""

    def covers(self, granularity: EntityType) -> bool:
        """Whether this table knows *any* alias at ``granularity``."""
        ...

    def find(self, text: str, granularity: EntityType) -> str | None:
        """The first alias at ``granularity`` occurring in ``text``, if any."""
        ...


class StaticAliasTable:
    """An in-memory ``AliasTable`` built from an explicit mapping.

    Matching is case-insensitive and word-bounded, so "Oregon" matches
    "oregon coast" but not "Oregonian".
    """

    def __init__(self, aliases: Mapping[EntityType, Iterable[str]] | None = None) -> None:
        self._patterns: dict[EntityType, list[tuple[str, re.Pattern[str]]]] = {}
        for granularity, names in (aliases or {}).items():
            compiled = [
                (name, re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE))
                for name in names
                if name.strip()
            ]
            if compiled:
                self._patterns[granularity] = compiled

    def covers(self, granularity: EntityType) -> bool:
        return granularity in self._patterns

    def find(self, text: str, granularity: EntityType) -> str | None:
        for name, pattern in self._patterns.get(granularity, ()):
            if pattern.search(text):
                return name
        return None
