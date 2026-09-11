"""The §7.1 status table (plan §0.1 rule 4).

The load-bearing test here is the last one: a degraded run and a genuinely
thin one must never be described in the same words. Everything else in the
system can be correct and the product still lies if these two strings
converge.
"""

from __future__ import annotations

import re

import pytest

from tripfinder.api.messages import (
    FAILURE_MESSAGES,
    PROGRESS_FLAVOR,
    STATUS_MESSAGES,
    percentages_suppressed,
    research_message,
    status_message,
)
from tripfinder.domain.models import FailureKind, ResearchFailure, ResearchStatus

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


class TestProgressFlavor:
    """Loading-stage copy only — plan §0.1 rule 4 governs the terminal §7.1
    outcomes, not "what is happening right now" text."""

    _NOT_FLAVORED = frozenset(
        {
            ResearchStatus.NEEDS_CLARIFICATION,
            ResearchStatus.REJECTED,
            ResearchStatus.COMPLETED,
            ResearchStatus.COMPLETED_PARTIAL,
            ResearchStatus.COMPLETED_DEGRADED,
            ResearchStatus.SOURCE_UNAVAILABLE,
            ResearchStatus.FAILED,
            ResearchStatus.CANCELLED,
        }
    )

    def test_flavor_never_covers_a_terminal_or_prompt_status(self) -> None:
        assert set(PROGRESS_FLAVOR).isdisjoint(self._NOT_FLAVORED)

    @pytest.mark.parametrize("status", list(PROGRESS_FLAVOR))
    def test_every_variant_is_non_empty_prose(self, status: ResearchStatus) -> None:
        assert all(variant.strip() for variant in PROGRESS_FLAVOR[status])

    @pytest.mark.parametrize("status", list(PROGRESS_FLAVOR))
    def test_a_flavored_status_never_returns_outside_its_own_variants(
        self, status: ResearchStatus
    ) -> None:
        seen = {research_message(status) for _ in range(50)}

        assert seen <= set(PROGRESS_FLAVOR[status])

    def test_an_unflavored_status_returns_its_plain_wording_every_time(self) -> None:
        for _ in range(10):
            assert research_message(ResearchStatus.COMPLETED) == status_message(
                ResearchStatus.COMPLETED
            )

    def test_a_failed_run_with_a_named_cause_ignores_flavor_entirely(self) -> None:
        """``FAILED`` has no flavor variants, so this would already be true —
        but the failure-cause branch must still be checked first regardless."""
        failure = ResearchFailure(kind=FailureKind.LLM_UNAVAILABLE, step="x", detail="why")

        assert research_message(ResearchStatus.FAILED, failure) == FAILURE_MESSAGES[
            FailureKind.LLM_UNAVAILABLE
        ]


class TestPercentageSuppression:
    """Two reasons to withhold a share, and no third one.

    §8.1 rule 2: a degraded run's denominator is not a sample. Plan
    §2.13.1: a provisional run's denominator is not closed yet. Every other
    status either has a real denominator or has no results object at all.
    """

    def test_a_degraded_run_and_an_unfinished_one_suppress_percentages(self) -> None:
        suppressing = {
            status for status in ResearchStatus if percentages_suppressed(status)
        }

        assert suppressing == {
            ResearchStatus.COMPLETED_DEGRADED,
            ResearchStatus.ANALYZING,
            ResearchStatus.CANCELLED,
        }

    def test_a_finished_run_never_suppresses_them(self) -> None:
        for status in (ResearchStatus.COMPLETED, ResearchStatus.COMPLETED_PARTIAL):
            assert not percentages_suppressed(status)


class TestAFailedRunNamesItsCause:
    """Plan §0.1 rule 3 — a short or empty result set must name its cause.

    `ResearchStatus.FAILED`'s own wording says only that nothing was
    produced. These say why, and none of them may be mistakable for a run
    that looked properly and found little.
    """

    def test_every_failure_kind_has_a_message(self) -> None:
        assert set(FAILURE_MESSAGES) == set(FailureKind)

    def test_no_two_failure_kinds_share_a_message(self) -> None:
        messages = list(FAILURE_MESSAGES.values())

        assert len(set(messages)) == len(messages)

    @pytest.mark.parametrize("kind", list(FailureKind))
    def test_a_failure_message_shares_no_wording_with_a_completed_run(
        self, kind: FailureKind
    ) -> None:
        """The §0.1 rule-4 assertion, applied to failures as well as degradation."""
        completed = status_message(ResearchStatus.COMPLETED)

        shared = _content_words(FAILURE_MESSAGES[kind]) & _content_words(completed)

        assert shared == set(), f"{kind} shares wording with completed: {shared}"

    @pytest.mark.parametrize("kind", list(FailureKind))
    def test_a_failure_message_replaces_the_generic_one(self, kind: FailureKind) -> None:
        failure = ResearchFailure(kind=kind, step="query_understanding", detail="why")

        message = research_message(ResearchStatus.FAILED, failure)

        assert message == FAILURE_MESSAGES[kind]
        assert message != status_message(ResearchStatus.FAILED)

    def test_a_failure_without_a_named_cause_falls_back_to_the_status_wording(self) -> None:
        assert research_message(ResearchStatus.FAILED) == status_message(ResearchStatus.FAILED)

    @pytest.mark.parametrize(
        "status", [ResearchStatus.COMPLETED, ResearchStatus.COMPLETED_DEGRADED]
    )
    def test_a_failure_recorded_on_a_non_failed_run_never_rewrites_its_message(
        self, status: ResearchStatus
    ) -> None:
        """Only a `failed` run is described by its failure. Nothing else is."""
        failure = ResearchFailure(
            kind=FailureKind.LLM_UNAVAILABLE, step="analysis", detail="why"
        )

        assert research_message(status, failure) == status_message(status)

    def test_the_credential_message_blames_configuration_not_the_topic(self) -> None:
        message = FAILURE_MESSAGES[FailureKind.LLM_CREDENTIAL]

        assert "configuration" in message
        assert "not a quiet topic" in message
