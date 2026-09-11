"""Verifying that a supporting quote really is in the comment (plan §5, §2.12.1).

`PROJECT.md` §29 forbids inventing evidence, and the mechanism is this: a
mention is only evidence if a human can find its quote in the comment it
came from. Phase 8 enforced that as an exact substring test, which is
correct and slightly too literal.

**What the measurement showed.** Nine discarded mentions from the measured
run were read by hand against their comments. Six contained the named place
and failed only on formatting — a doubled space, a parenthesis
(``Hot Springs (National Park)``), capitalisation. Three did not:

* a comment praising *"the shore of Lake Huron"* produced a mention of
  **Lake Michigan** — a real person's real opinion, attached to the wrong
  place, in the run whose top result was Michigan;
* a comment about Michigan mosquitoes and South Haven produced a mention of
  **Detroit**, a city it never names.

Neither invented a *place*; both invented an *attribution*, and both are
invisible afterwards because the number, the source and the person are all
real. That is what the rule exists to catch, and why it is not relaxed into
a judgement call.

**So the rule is loosened, not removed.** Normalise both sides — case,
whitespace runs, typographic quotes and dashes — then accept at
``similarity_threshold`` (0.90) and discard below it. The check stays
deterministic, which an LLM self-assessment could not: the model that wrote
``Lake Michigan`` wrote it confidently.

Every non-exact decision is written to an audit trail, accepted and rejected
alike. Without it the threshold is a guess nobody can revisit — the two
questions worth asking later are "what was admitted just above the line that
should not have been" and "what was dropped just below it that should have
stayed", and both need the borderline cases kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

_TYPOGRAPHY = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2033": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u00a0": " ",
    }
)
"""Curly quotes, the dash family and the non-breaking space, folded to ASCII.

Deliberately narrow. Punctuation is *not* stripped the way
``normalization.normalization_key`` strips it: a quote has to stay findable
in the original comment by a human, and a rule that deleted punctuation
would accept spans nobody could locate.
"""


def normalize_quote(text: str) -> str:
    """Case-folded, with whitespace runs collapsed and typography flattened."""
    return " ".join(text.translate(_TYPOGRAPHY).casefold().split())


@dataclass(frozen=True)
class QuoteMatch:
    """How well a claimed quote matches the comment it claims to come from."""

    similarity: float
    """0.0-1.0. 1.0 means the normalised quote appears in the normalised body."""

    matched_span: str
    """The best-matching stretch of the comment, normalised. Empty when nothing matched."""

    exact: bool
    """True when the raw quote is a raw substring — no normalisation needed, nothing to audit."""


def verify_quote(quote: str, body: str) -> QuoteMatch:
    """Locate ``quote`` in ``body``, tolerating formatting but not invention.

    The span is reported normalised, which is what the comparison actually
    ran on. It differs from the comment only in case, spacing and
    typography, so it still leads a reader to the right place.
    """
    if quote and quote in body:
        return QuoteMatch(similarity=1.0, matched_span=quote, exact=True)

    needle = normalize_quote(quote)
    haystack = normalize_quote(body)
    if not needle or not haystack:
        return QuoteMatch(similarity=0.0, matched_span="", exact=False)
    if needle in haystack:
        return QuoteMatch(similarity=1.0, matched_span=needle, exact=False)

    return _best_window(needle, haystack)


def _best_window(needle: str, haystack: str) -> QuoteMatch:
    """The stretch of ``haystack`` most like ``needle``, and how alike it is.

    Anchored on the longest shared run rather than scanning every offset:
    a quote that shares no long run with the comment is the invented-
    attribution case, and it scores low wherever it is placed.
    """
    matcher = SequenceMatcher(None, haystack, needle, autojunk=False)
    anchor = matcher.find_longest_match(0, len(haystack), 0, len(needle))
    if anchor.size == 0:
        return QuoteMatch(similarity=0.0, matched_span="", exact=False)

    start = max(0, anchor.a - anchor.b)
    slack = len(needle) // 10 + 1
    best = QuoteMatch(similarity=0.0, matched_span="", exact=False)
    for pad in (0, slack):
        window = haystack[max(0, start - pad) : start + len(needle) + pad]
        if not window:
            continue
        similarity = SequenceMatcher(None, window, needle, autojunk=False).ratio()
        if similarity > best.similarity:
            best = QuoteMatch(similarity=similarity, matched_span=window, exact=False)
    return best
