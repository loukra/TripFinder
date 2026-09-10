"""The §7.1 status table (plan §0.1 rule 4).

The load-bearing test here is the last one: a degraded run and a genuinely
thin one must never be described in the same words. Everything else in the
system can be correct and the product still lies if these two strings
converge.
"""

from __future__ import annotations

import re

import pytest

from tripfinder.api.messages import STATUS_MESSAGES, percentages_suppressed, status_message
from tripfinder.domain.models import ResearchStatus

_STOPWORDS = frozenset(
    """a an and are as at be been before but by can cannot did do does for from had has have
    if in is it its may no not of on or so than that the them there these they this to too was
    we were what when which while who will with you your""".split()
)


def _content_words(message: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]+", message.lower()) if word not in _STOPWORDS}


def test_every_status_has_a_message() -> None:
    assert set(STATUS_MESSAGES) == set(ResearchStatus)


def test_no_two_statuses_share_a_message() -> None:
    messages = list(STATUS_MESSAGES.values())

    assert len(set(messages)) == len(messages)


@pytest.mark.parametrize("status", list(ResearchStatus))
def test_every_message_is_non_empty_prose(status: ResearchStatus) -> None:
    assert status_message(status).strip()


class TestDegradedIsNeverMistakenForThin:
    """The §2.7 regression: a failure must never masquerade as a finding."""

    def test_a_degraded_run_is_not_described_like_a_completed_one(self) -> None:
        degraded = status_message(ResearchStatus.COMPLETED_DEGRADED)
        completed = status_message(ResearchStatus.COMPLETED)

        assert degraded != completed

        # Not merely different strings: they may not share a content word.
        # Strict on purpose — this is the assertion that fails the build if a
        # future copy edit lets the two outcomes start sounding alike.
        shared = _content_words(degraded) & _content_words(completed)
        assert shared == set(), f"degraded and completed share wording: {shared}"

    def test_a_degraded_run_says_the_source_failed(self) -> None:
        degraded = status_message(ResearchStatus.COMPLETED_DEGRADED)

        assert "could not reach parts of the source" in degraded
        assert "percentages are withheld" in degraded

    def test_a_completed_run_never_blames_or_mentions_the_source(self) -> None:
        completed = status_message(ResearchStatus.COMPLETED)

        assert "could not" not in completed
        assert "failed" not in completed

    def test_partial_and_degraded_promise_different_things(self) -> None:
        """`partial` claims a valid sample; `degraded` claims nothing (§7.1)."""
        partial = status_message(ResearchStatus.COMPLETED_PARTIAL)
        degraded = status_message(ResearchStatus.COMPLETED_DEGRADED)

        assert "on purpose" in partial
        assert "on purpose" not in degraded

    def test_source_unavailable_promises_nothing_at_all(self) -> None:
        message = status_message(ResearchStatus.SOURCE_UNAVAILABLE)

        assert "no evidence" in message
        assert "nothing to conclude" in message


class TestPercentageSuppression:
    def test_only_a_degraded_run_suppresses_percentages(self) -> None:
        suppressing = {
            status for status in ResearchStatus if percentages_suppressed(status)
        }

        assert suppressing == {ResearchStatus.COMPLETED_DEGRADED}
