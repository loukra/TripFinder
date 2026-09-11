"""Quote verification (plan §5, §2.12.1).

The cases are the ones the plan was written from: nine discards read by hand
against their comments, six formatting misses and three invented
attributions. The threshold is only defensible if it separates them, so that
is what is asserted here rather than a set of invented strings.
"""

from __future__ import annotations

import pytest

from tripfinder.analysis.quote_verification import normalize_quote, verify_quote
from tripfinder.domain.config import QuoteVerificationConfig

THRESHOLD = QuoteVerificationConfig().similarity_threshold

HURON = "Honestly the shore of Lake Huron is the most underrated place in the midwest."
MOSQUITOES = "Michigan mosquitoes are brutal but South Haven is lovely in September."
HOT_SPRINGS = "I loved Hot Springs National Park, the trails were completely empty."


class TestAnExactQuoteNeedsNoTolerance:
    def test_a_verbatim_substring_matches_exactly(self) -> None:
        match = verify_quote("the shore of Lake Huron", HURON)

        assert match.exact is True
        assert match.similarity == 1.0

    def test_an_empty_quote_matches_nothing(self) -> None:
        match = verify_quote("", HURON)

        assert match.exact is False
        assert match.similarity == 0.0

    def test_an_empty_body_matches_nothing(self) -> None:
        assert verify_quote("anything at all", "").similarity == 0.0


class TestFormattingMissesAreRecovered:
    """The six of nine that genuinely contained the named place."""

    @pytest.mark.parametrize(
        ("quote", "body"),
        [
            ("I loved  Hot  Springs  National  Park", HOT_SPRINGS),
            ("i loved hot springs national park", HOT_SPRINGS),
            ("Hot Springs (National Park)", HOT_SPRINGS),
            ("\u201cthe shore of Lake Huron\u201d", HURON),
            ("South Haven is lovely \u2014 in September", MOSQUITOES),
        ],
    )
    def test_it_is_accepted(self, quote: str, body: str) -> None:
        assert verify_quote(quote, body).similarity >= THRESHOLD

    def test_normalisation_alone_settles_whitespace_case_and_typography(self) -> None:
        assert normalize_quote("  The \u201cBeaver\u201d  State \u2014 really  ") == (
            'the "beaver" state - really'
        )

    def test_a_recovered_quote_is_no_longer_flagged_as_exact(self) -> None:
        """It is a borderline decision, and borderline decisions get audited."""
        match = verify_quote("Hot Springs (National Park)", HOT_SPRINGS)

        assert match.exact is False
        assert match.matched_span


class TestInventedAttributionsAreStillRejected:
    """The three of nine that are the reason the rule exists at all.

    Neither invents a *place*; both invent an *attribution*, and both are
    invisible afterwards because the number, the source and the person are
    all real.
    """

    def test_a_neighbouring_lake_is_not_the_lake_that_was_named(self) -> None:
        match = verify_quote("the shore of Lake Michigan", HURON)

        assert match.similarity < THRESHOLD

    def test_a_city_the_comment_never_names_is_rejected(self) -> None:
        match = verify_quote("Detroit is worth a visit", MOSQUITOES)

        assert match.similarity < THRESHOLD

    def test_a_plausible_sentence_from_nowhere_is_rejected(self) -> None:
        match = verify_quote("Everyone should visit Wyoming in the autumn", HURON)

        assert match.similarity < THRESHOLD


class TestTheCheckIsDeterministic:
    def test_the_same_pair_scores_the_same_every_time(self) -> None:
        """An LLM self-assessment could not promise this — the model that wrote
        "Lake Michigan" wrote it confidently."""
        scores = {verify_quote("the shore of Lake Michigan", HURON).similarity for _ in range(5)}

        assert len(scores) == 1

    def test_punctuation_is_folded_but_never_stripped(self) -> None:
        """A rule that deleted punctuation would accept spans nobody could find."""
        assert normalize_quote("Hot Springs (National Park)") == "hot springs (national park)"
