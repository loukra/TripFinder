from __future__ import annotations

from tripfinder.analysis.aliases import AliasTable, StaticAliasTable
from tripfinder.domain.models import EntityType


def test_static_table_satisfies_the_alias_table_port() -> None:
    assert isinstance(StaticAliasTable(), AliasTable)


def test_finds_an_alias_case_insensitively() -> None:
    table = StaticAliasTable({EntityType.STATE: ["Alaska", "Oregon"]})

    assert table.find("alaska is underrated, right?", EntityType.STATE) == "Alaska"
    assert table.find("Best of the OREGON coast", EntityType.STATE) == "Oregon"


def test_matches_on_word_boundaries_only() -> None:
    table = StaticAliasTable({EntityType.STATE: ["Oregon"]})

    assert table.find("an Oregonian tradition", EntityType.STATE) is None


def test_does_not_match_an_alias_from_another_granularity() -> None:
    table = StaticAliasTable({EntityType.STATE: ["Alaska"], EntityType.PARK: ["Denali"]})

    assert table.find("Denali in autumn", EntityType.STATE) is None
    assert table.find("Denali in autumn", EntityType.PARK) == "Denali"


def test_covers_reports_which_tiers_the_table_can_speak_to() -> None:
    table = StaticAliasTable({EntityType.STATE: ["Alaska"]})

    assert table.covers(EntityType.STATE) is True
    assert table.covers(EntityType.PARK) is False


def test_an_empty_table_covers_nothing() -> None:
    """The signal triage needs to fall through to AI rather than guess (plan §4.7)."""
    assert StaticAliasTable().covers(EntityType.STATE) is False
    assert StaticAliasTable({EntityType.STATE: ["  "]}).covers(EntityType.STATE) is False
