"""Deterministic name normalization (plan §4.6 step 8, first half).

`PROJECT.md` §27 Phase 9 asks for spelling differences to resolve. Most of
them are orthographic — an accent, an apostrophe, a capital, a stray "the"
— and this is where those are folded away. What is *not* here matters just
as much: nothing in this module can decide two different names are the same
place.
"""

from __future__ import annotations

import pytest

from tripfinder.analysis.normalization import normalization_key, slug


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Alaska", "alaska"),
        ("ALASKA", "alaska"),
        ("  Alaska  ", "alaska"),
        ("New   Mexico", "new mexico"),
        ("New-Mexico", "new mexico"),
    ],
)
def test_folds_case_and_spacing(written: str, expected: str) -> None:
    assert normalization_key(written) == expected


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Hawai'i", "hawaii"),
        ("Hawai’i", "hawaii"),
        ("Québec", "quebec"),
        ("Nuuk, Greenland", "nuuk greenland"),
        ("St. Louis", "st louis"),
    ],
)
def test_folds_accents_and_punctuation(written: str, expected: str) -> None:
    """An apostrophe joins a word; a period or comma separates one."""
    assert normalization_key(written) == expected


@pytest.mark.parametrize(
    "written", ["The Last Frontier", "the last frontier", "Last Frontier", "THE Last Frontier"]
)
def test_a_leading_article_does_not_change_the_name(written: str) -> None:
    assert normalization_key(written) == "last frontier"


def test_an_article_inside_the_name_survives() -> None:
    """Only a *leading* "the" is decoration — "Land of the Midnight Sun" is not."""
    assert normalization_key("Land of the Midnight Sun") == "land of the midnight sun"


def test_a_string_with_no_name_in_it_has_no_key() -> None:
    """An empty key must never be treated as a match — it would match everything."""
    assert normalization_key("!!!") == ""
    assert normalization_key("   ") == ""


def test_different_names_keep_different_keys() -> None:
    """The whole safety property: this module folds spellings, never places."""
    assert normalization_key("Alaska") != normalization_key("AK")
    assert normalization_key("Virginia") != normalization_key("West Virginia")
    assert normalization_key("Washington") != normalization_key("Washington DC")


def test_slug_is_the_key_with_dashes_and_depends_on_the_name_alone() -> None:
    """Ranking's final tiebreak is the id (plan §4.3), so it cannot vary per run."""
    assert slug("New Mexico") == "new-mexico"
    assert slug("The Last Frontier") == slug("the last frontier")
