"""The alias table (plan §4.6 step 8, §4.5 rule 1).

Covers the two questions one body of data has to answer — *what entity is
this name?* for resolution, and *does this title name an entity?* for
triage — and the rule that protects both: more than one match is an answer
of "ambiguous", never a pick.
"""

from __future__ import annotations

from tripfinder.analysis.aliases import AliasTable
from tripfinder.analysis.entities import Alias, CatalogEntry, EntityCatalog
from tripfinder.domain.models import EntityType

ALASKA = CatalogEntry(
    canonical_name="Alaska",
    entity_type=EntityType.STATE,
    aliases=(Alias("AK", case_sensitive=True), Alias("The Last Frontier")),
)
OREGON = CatalogEntry(
    canonical_name="Oregon",
    entity_type=EntityType.STATE,
    aliases=(Alias("OR", case_sensitive=True), Alias("The Beaver State")),
)
DENALI = CatalogEntry(canonical_name="Denali National Park", entity_type=EntityType.PARK)

CATALOG = EntityCatalog([ALASKA, OREGON, DENALI])


class TestLookup:
    def test_resolves_a_canonical_name(self) -> None:
        assert CATALOG.lookup("Alaska", EntityType.STATE) == (ALASKA,)

    def test_resolves_an_alias(self) -> None:
        """`PROJECT.md` §15's own example: a nickname is the same entity."""
        assert CATALOG.lookup("The Last Frontier", EntityType.STATE) == (ALASKA,)
        assert CATALOG.lookup("the last frontier", EntityType.STATE) == (ALASKA,)

    def test_resolves_an_abbreviation_written_as_an_abbreviation(self) -> None:
        assert CATALOG.lookup("AK", EntityType.STATE) == (ALASKA,)
        assert CATALOG.lookup("AK.", EntityType.STATE) == (ALASKA,)

    def test_does_not_resolve_an_abbreviation_written_as_a_word(self) -> None:
        """*or* is a conjunction far more often than it is Oregon."""
        assert CATALOG.lookup("or", EntityType.STATE) == ()

    def test_resolves_across_a_spelling_difference(self) -> None:
        catalog = EntityCatalog([CatalogEntry("Hawaii", EntityType.STATE)])

        assert catalog.lookup("Hawai'i", EntityType.STATE)[0].canonical_name == "Hawaii"

    def test_an_unknown_name_resolves_to_nothing(self) -> None:
        assert CATALOG.lookup("Vermont", EntityType.STATE) == ()

    def test_a_name_shared_by_two_places_returns_both(self) -> None:
        """Ambiguity is reported, not decided (`PROJECT.md` §15)."""
        springfield_or = CatalogEntry(
            "Springfield, Oregon", EntityType.CITY, (Alias("Springfield"),)
        )
        springfield_il = CatalogEntry(
            "Springfield, Illinois", EntityType.CITY, (Alias("Springfield"),)
        )
        catalog = EntityCatalog([springfield_or, springfield_il])

        assert catalog.lookup("Springfield", EntityType.CITY) == (springfield_or, springfield_il)

    def test_does_not_cross_tiers(self) -> None:
        assert CATALOG.lookup("Denali National Park", EntityType.STATE) == ()
        assert CATALOG.lookup("Denali National Park", EntityType.PARK) == (DENALI,)

    def test_an_empty_name_resolves_to_nothing(self) -> None:
        assert CATALOG.lookup("   ", EntityType.STATE) == ()
        assert CATALOG.lookup("???", EntityType.STATE) == ()


class TestTriageInterface:
    def test_a_catalog_is_an_alias_table(self) -> None:
        """§4.5 rule 1 runs against this same data (plan §4.5)."""
        assert isinstance(CATALOG, AliasTable)

    def test_finds_a_name_inside_a_title(self) -> None:
        assert CATALOG.find("Alaska is underrated, right?", EntityType.STATE) == "Alaska"
        assert CATALOG.find("Why the Beaver State wins", EntityType.STATE) == "Oregon"

    def test_finds_nothing_in_an_open_question(self) -> None:
        assert CATALOG.find("Most underrated state for nature?", EntityType.STATE) is None

    def test_does_not_read_an_abbreviation_out_of_an_ordinary_word(self) -> None:
        """The bug this guards: "state or province" is not a thread about Oregon."""
        assert CATALOG.find("Best state or province for hiking?", EntityType.STATE) is None

    def test_reads_an_uppercase_abbreviation(self) -> None:
        assert CATALOG.find("Roadtripping AK next June", EntityType.STATE) == "Alaska"

    def test_covers_reports_which_tiers_it_can_speak_for(self) -> None:
        assert CATALOG.covers(EntityType.STATE) is True
        assert CATALOG.covers(EntityType.PARK) is True
        assert CATALOG.covers(EntityType.ISLAND) is False

    def test_an_empty_catalog_covers_nothing(self) -> None:
        assert EntityCatalog().covers(EntityType.STATE) is False


class TestIdentity:
    def test_a_canonical_id_is_derived_from_the_name(self) -> None:
        assert ALASKA.canonical_id == "state:alaska"
        assert CatalogEntry("New Mexico", EntityType.STATE).canonical_id == "state:new-mexico"

    def test_the_entity_carries_its_aliases(self) -> None:
        entity = ALASKA.as_entity()

        assert entity.canonical_name == "Alaska"
        assert entity.entity_type is EntityType.STATE
        assert entity.aliases == ["AK", "The Last Frontier"]

    def test_entries_at_lists_one_tier(self) -> None:
        assert CATALOG.entries_at(EntityType.PARK) == (DENALI,)
        assert CATALOG.entries_at(EntityType.ISLAND) == ()
