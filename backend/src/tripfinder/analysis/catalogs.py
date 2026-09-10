"""The entity data this MVP ships — US states, at the ``state`` tier.

Plan §4.6 step 8 resolves *deterministically first*, and a deterministic
step can only resolve names it has been given. This is that data: the fifty
US states, each with its postal abbreviation and the nicknames people
actually use in the threads this project reads — *"the Beaver State"*,
*"the Last Frontier"*, *"the Great Lakes State"*.

Why this tier and no other: every benchmark query in plan §15 that names a
tier at all names states, the plan's own worked examples are states
(§4.5's *"Alaska is underrated"*), and fifty entries with fixed
abbreviations is a set that can be written down completely and correctly.
Parks, regions and cities are open-ended, and half a catalogue is worse
than none — it would resolve the famous names and quietly send the rest to
the model, making resolution quality depend on fame. Those tiers go to the
model in full, and the catalogue's ``covers`` tells every caller which
tier it can and cannot speak for.

The District of Columbia is deliberately absent: it is not a state, and
adding it here would let a query about states count it as one.
"""

from __future__ import annotations

from functools import cache

from tripfinder.analysis.entities import Alias, CatalogEntry, EntityCatalog
from tripfinder.domain.models import EntityType

_US_STATES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Alabama", "AL", ("Yellowhammer State",)),
    ("Alaska", "AK", ("The Last Frontier",)),
    ("Arizona", "AZ", ("Grand Canyon State",)),
    ("Arkansas", "AR", ("The Natural State",)),
    ("California", "CA", ("Golden State",)),
    ("Colorado", "CO", ("Centennial State",)),
    ("Connecticut", "CT", ("Constitution State",)),
    ("Delaware", "DE", ("First State",)),
    ("Florida", "FL", ("Sunshine State",)),
    ("Georgia", "GA", ("Peach State",)),
    ("Hawaii", "HI", ("Aloha State",)),
    ("Idaho", "ID", ("Gem State",)),
    ("Illinois", "IL", ("Prairie State",)),
    ("Indiana", "IN", ("Hoosier State",)),
    ("Iowa", "IA", ("Hawkeye State",)),
    ("Kansas", "KS", ("Sunflower State",)),
    ("Kentucky", "KY", ("Bluegrass State",)),
    ("Louisiana", "LA", ("Pelican State",)),
    ("Maine", "ME", ("Pine Tree State",)),
    ("Maryland", "MD", ("Old Line State",)),
    ("Massachusetts", "MA", ("Bay State",)),
    ("Michigan", "MI", ("Great Lakes State", "Wolverine State")),
    ("Minnesota", "MN", ("North Star State", "Land of 10,000 Lakes")),
    ("Mississippi", "MS", ("Magnolia State",)),
    ("Missouri", "MO", ("Show Me State",)),
    ("Montana", "MT", ("Treasure State", "Big Sky Country")),
    ("Nebraska", "NE", ("Cornhusker State",)),
    ("Nevada", "NV", ("Silver State",)),
    ("New Hampshire", "NH", ("Granite State",)),
    ("New Jersey", "NJ", ("Garden State",)),
    ("New Mexico", "NM", ("Land of Enchantment",)),
    ("New York", "NY", ("Empire State",)),
    ("North Carolina", "NC", ("Tar Heel State",)),
    ("North Dakota", "ND", ("Peace Garden State",)),
    ("Ohio", "OH", ("Buckeye State",)),
    ("Oklahoma", "OK", ("Sooner State",)),
    ("Oregon", "OR", ("Beaver State",)),
    ("Pennsylvania", "PA", ("Keystone State",)),
    ("Rhode Island", "RI", ("Ocean State",)),
    ("South Carolina", "SC", ("Palmetto State",)),
    ("South Dakota", "SD", ("Mount Rushmore State",)),
    ("Tennessee", "TN", ("Volunteer State",)),
    ("Texas", "TX", ("Lone Star State",)),
    ("Utah", "UT", ("Beehive State",)),
    ("Vermont", "VT", ("Green Mountain State",)),
    ("Virginia", "VA", ("Old Dominion",)),
    ("Washington", "WA", ("Evergreen State",)),
    ("West Virginia", "WV", ("Mountain State",)),
    ("Wisconsin", "WI", ("Badger State",)),
    ("Wyoming", "WY", ("Equality State", "Cowboy State")),
)


def _state_entry(name: str, abbreviation: str, nicknames: tuple[str, ...]) -> CatalogEntry:
    return CatalogEntry(
        canonical_name=name,
        entity_type=EntityType.STATE,
        aliases=(
            Alias(abbreviation, case_sensitive=True),
            Alias(f"{name} State"),
            *(Alias(nickname) for nickname in nicknames),
        ),
    )


def us_state_entries() -> tuple[CatalogEntry, ...]:
    """The fifty states as catalogue entries, in alphabetical order."""
    return tuple(
        _state_entry(name, abbreviation, nicknames)
        for name, abbreviation, nicknames in _US_STATES
    )


@cache
def default_catalog() -> EntityCatalog:
    """The catalogue a research uses when the caller supplies none.

    Cached: it is immutable, identical for every research, and building it
    compiles a few hundred patterns.
    """
    return EntityCatalog(us_state_entries())
