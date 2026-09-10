"""The alias table — second step of §4.6 step 8, and §4.5's triage rule.

``analysis/aliases.py`` declared the :class:`~tripfinder.analysis.aliases.AliasTable`
interface in Phase 7 and said Phase 9 would supply the populated table
behind it. This is that table, and it does two jobs from one body of data:

* **Resolution** (§4.6 step 8) asks *what entity is this mention?* —
  :meth:`EntityCatalog.lookup`, an exact match on a normalized name.
* **Triage** (§4.5 rule 1) asks *does this title name an entity?* —
  :meth:`EntityCatalog.find`, a word-bounded search inside a title.

Both run before any model is asked anything, and everything they settle is
a call the model never has to make.

**Abbreviations are matched case-sensitively.** A two-letter postal code is
also an ordinary English word — *OR*, *IN*, *ME*, *HI*, *OK* — and a
case-insensitive search for one inside a title would read *"Which state or
province?"* as a mention of Oregon. Uppercase is the only thing that
separates the abbreviation from the word, so it is required.

**A miss is a miss, never a guess.** ``lookup`` returning nothing means
this table does not know the name, and ``find`` returning ``None`` means
the title contains no name it knows — which is why triage checks
``covers`` first, and why resolution sends its misses to the model rather
than inventing an entity for them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from tripfinder.analysis.normalization import normalization_key, slug
from tripfinder.domain.models import Entity, EntityType


@dataclass(frozen=True)
class Alias:
    """One way of writing an entity's name.

    ``case_sensitive`` marks a form that only means the place when written
    exactly so — postal abbreviations, and nothing else so far.
    """

    text: str
    case_sensitive: bool = False


@dataclass(frozen=True)
class CatalogEntry:
    """A canonical entity and every name this table knows it by."""

    canonical_name: str
    entity_type: EntityType
    aliases: tuple[Alias, ...] = field(default_factory=tuple)

    @property
    def canonical_id(self) -> str:
        """Derived from the name, so it is identical on every run (plan §4.3)."""
        return f"{self.entity_type.value}:{slug(self.canonical_name)}"

    def all_aliases(self) -> tuple[Alias, ...]:
        """The canonical name first, then the alternatives."""
        return (Alias(self.canonical_name), *self.aliases)

    def as_entity(self) -> Entity:
        return Entity(
            canonical_id=self.canonical_id,
            canonical_name=self.canonical_name,
            entity_type=self.entity_type,
            aliases=[alias.text for alias in self.aliases],
        )


class EntityCatalog:
    """Known entities, indexed by tier and by every name they answer to.

    Satisfies :class:`~tripfinder.analysis.aliases.AliasTable`, so triage
    can take one of these directly (plan §4.5 rule 1).
    """

    def __init__(self, entries: Iterable[CatalogEntry] = ()) -> None:
        self._entries: dict[EntityType, list[CatalogEntry]] = {}
        self._by_key: dict[EntityType, dict[str, list[CatalogEntry]]] = {}
        self._by_exact: dict[EntityType, dict[str, list[CatalogEntry]]] = {}
        self._patterns: dict[EntityType, list[tuple[str, re.Pattern[str]]]] = {}

        for entry in entries:
            self._entries.setdefault(entry.entity_type, []).append(entry)
            for alias in entry.all_aliases():
                self._index(entry, alias)

    def _index(self, entry: CatalogEntry, alias: Alias) -> None:
        tier = entry.entity_type
        if alias.case_sensitive:
            exact = self._by_exact.setdefault(tier, {})
            _append_unique(exact.setdefault(alias.text, []), entry)
            flags = 0
        else:
            key = normalization_key(alias.text)
            if not key:
                return
            keyed = self._by_key.setdefault(tier, {})
            _append_unique(keyed.setdefault(key, []), entry)
            flags = re.IGNORECASE
        pattern = re.compile(rf"\b{re.escape(alias.text)}\b", flags)
        self._patterns.setdefault(tier, []).append((entry.canonical_name, pattern))

    # -- AliasTable ----------------------------------------------------

    def covers(self, granularity: EntityType) -> bool:
        """Whether this catalog knows *any* entity at ``granularity``."""
        return granularity in self._entries

    def find(self, text: str, granularity: EntityType) -> str | None:
        """The canonical name of the first entity ``text`` names, if any."""
        for canonical_name, pattern in self._patterns.get(granularity, ()):
            if pattern.search(text):
                return canonical_name
        return None

    # -- resolution ----------------------------------------------------

    def lookup(self, text: str, granularity: EntityType) -> tuple[CatalogEntry, ...]:
        """Every entity at ``granularity`` that ``text`` could be naming.

        Empty means unknown. **More than one means ambiguous** — the caller
        must not pick one, because picking is the silent merge `PROJECT.md`
        §15 forbids.
        """
        matches: list[CatalogEntry] = []
        for entry in self._by_exact.get(granularity, {}).get(text.strip(" .,"), ()):
            _append_unique(matches, entry)
        key = normalization_key(text)
        if key:
            for entry in self._by_key.get(granularity, {}).get(key, ()):
                _append_unique(matches, entry)
        return tuple(matches)

    def entries_at(self, granularity: EntityType) -> tuple[CatalogEntry, ...]:
        """Every entity this catalog holds at one tier, in insertion order."""
        return tuple(self._entries.get(granularity, ()))


def _append_unique(entries: list[CatalogEntry], entry: CatalogEntry) -> None:
    if entry not in entries:
        entries.append(entry)
