"""The shipped US-state catalogue (plan §4.6 step 8).

Data, so the tests are about the data: that it is complete, that no two
states answer to the same name, and that the abbreviations cannot be read
out of ordinary prose. A wrong entry here is not a crash — it is a silently
miscounted state — so it is checked rather than assumed.
"""

from __future__ import annotations

from tripfinder.analysis.catalogs import default_catalog, us_state_entries
from tripfinder.analysis.normalization import normalization_key
from tripfinder.domain.models import EntityType

CATALOG = default_catalog()
ENTRIES = us_state_entries()


def test_ships_all_fifty_states() -> None:
    assert len(ENTRIES) == 50


def test_the_district_of_columbia_is_not_among_them() -> None:
    """It is not a state, and a question about states must not count it as one."""
    assert CATALOG.lookup("District of Columbia", EntityType.STATE) == ()
    assert CATALOG.lookup("Washington DC", EntityType.STATE) == ()


def test_every_canonical_id_is_unique_and_derived_from_the_name() -> None:
    ids = [entry.canonical_id for entry in ENTRIES]

    assert len(set(ids)) == len(ids)
    assert "state:west-virginia" in ids


def test_no_name_is_shared_by_two_states() -> None:
    """Any duplicate would make a real state permanently unresolvable."""
    ambiguous = {
        alias.text
        for entry in ENTRIES
        for alias in entry.all_aliases()
        if len(CATALOG.lookup(alias.text, EntityType.STATE)) > 1
    }

    assert ambiguous == set()


def test_resolves_a_name_an_abbreviation_and_a_nickname_to_one_state() -> None:
    """`PROJECT.md` §15's worked example, end to end and with no model involved."""
    for written in ("Alaska", "alaska", "AK", "The Last Frontier", "the last frontier"):
        assert CATALOG.lookup(written, EntityType.STATE)[0].canonical_name == "Alaska"


def test_resolves_the_nickname_the_labeled_corpus_uses() -> None:
    """Phase 8's ``equivalent_wording`` fixture recommends "the Beaver State"."""
    assert CATALOG.lookup("the Beaver State", EntityType.STATE)[0].canonical_name == "Oregon"


def test_resolves_a_state_written_with_its_tier() -> None:
    assert CATALOG.lookup("Washington State", EntityType.STATE)[0].canonical_name == "Washington"


def test_resolves_an_apostrophe_spelling() -> None:
    assert CATALOG.lookup("Hawai'i", EntityType.STATE)[0].canonical_name == "Hawaii"


def test_a_lowercase_abbreviation_is_not_a_state() -> None:
    """*or*, *in*, *me*, *hi*, *ok*, *de*, *la*, *pa* are all ordinary words."""
    for written in ("or", "in", "me", "hi", "ok", "de", "la", "pa"):
        assert CATALOG.lookup(written, EntityType.STATE) == ()


def test_does_not_read_a_state_out_of_ordinary_prose() -> None:
    titles = [
        "Best state or province for hiking?",
        "Where should I go in June, me and two friends?",
        "Is it ok to camp here?",
    ]

    assert [CATALOG.find(title, EntityType.STATE) for title in titles] == [None, None, None]


def test_covers_states_and_nothing_else() -> None:
    """Triage falls through to the model for every tier this returns False for."""
    assert CATALOG.covers(EntityType.STATE) is True
    assert CATALOG.covers(EntityType.PARK) is False
    assert CATALOG.covers(EntityType.REGION) is False


def test_every_entry_carries_an_abbreviation_and_at_least_one_nickname() -> None:
    for entry in ENTRIES:
        texts = [alias.text for alias in entry.aliases]
        assert any(len(text) == 2 and text.isupper() for text in texts), entry.canonical_name
        assert len(texts) >= 3, entry.canonical_name


def test_no_nickname_is_just_the_state_name_again() -> None:
    """A nickname that folds onto the name adds nothing and hides a typo."""
    for entry in ENTRIES:
        name_key = normalization_key(entry.canonical_name)
        nicknames = [alias for alias in entry.aliases if not alias.case_sensitive]
        redundant = [
            alias.text
            for alias in nicknames
            if normalization_key(alias.text) == name_key
        ]
        assert redundant == [], entry.canonical_name


def test_the_default_catalog_is_the_same_object_every_time() -> None:
    """Immutable and identical per research — building it compiles a few hundred patterns."""
    assert default_catalog() is CATALOG
