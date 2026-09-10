"""Deterministic name normalization — the first step of §4.6 step 8.

Plan §4.6 orders entity resolution *deterministic normalization → alias
table → AI*, and this module is the first of the three. It answers one
question: **are these two strings the same name written differently?**

It answers it *orthographically only* — case, accents, punctuation,
spacing, a leading article. It never guesses at meaning: "AK" and "Alaska"
are different strings here, and the alias table is what knows they are the
same place. Nothing in this module can merge two entities, which is why
`PROJECT.md` §15's "never silently merge" rule has nothing to fear from it.

Deliberately absent: fuzzy or edit-distance matching. A near-miss between
two names is exactly the ambiguity plan §4.6 sends to the model, and
folding it away silently here would be a merge nobody could see.
"""

from __future__ import annotations

import re
import unicodedata

_LEADING_ARTICLE = re.compile(r"^(the)\s+", re.IGNORECASE)
_ELIDED = re.compile(r"[.'’ʼ]")
"""Marks that vanish rather than split a word: *Hawai'i* is one word, *St. Louis* two."""

_SEPARATORS = re.compile(r"[^0-9a-z]+")


def normalization_key(text: str) -> str:
    """A comparison key for a place name — the same for every spelling of it.

    Folds accents, case, punctuation and spacing, and drops a leading
    "the", so *"The Last Frontier"*, *"the last frontier"* and *"Last
    Frontier"* share a key, and so do *"Hawai'i"* and *"Hawaii"*.

    Returns ``""`` for a string with nothing name-like in it. An empty key
    matches nothing: callers must treat it as *unresolved*, never as a hit.
    """
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in folded if not unicodedata.combining(char))
    without_marks = _ELIDED.sub("", stripped).casefold()
    words = _SEPARATORS.sub(" ", without_marks).strip()
    return _LEADING_ARTICLE.sub("", words, count=1).strip()


def slug(text: str) -> str:
    """A stable, readable id fragment for a name — the key with dashes.

    Ranking's final tiebreak is the canonical id (plan §4.3), so this has
    to depend on the name alone: same name in, same id out, run after run.
    """
    return normalization_key(text).replace(" ", "-")
