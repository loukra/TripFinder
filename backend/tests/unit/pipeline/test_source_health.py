"""§8.1's outcome rules, applied to N adapters (plan §8.1, §0.1)."""

from __future__ import annotations

import pytest

from tripfinder.domain.config import SourceHealthFloors
from tripfinder.domain.models import ResearchStatus, SourceHealth, SourceOutcome
from tripfinder.pipeline.health import (
    SourceHealthRecorder,
    assess_source_health,
    terminal_status,
)
from tripfinder.sources.failures import UNKNOWN_FAILURE_KIND, failure_kind

FLOORS = SourceHealthFloors()

HEALTHY_POSTS = FLOORS.min_posts_retrieved + 5
HEALTHY_COMMENTS = FLOORS.min_comments_analyzed + 50


def _health(adapter: str, *, succeeded: int, failed: int, kind: str = "timeout") -> SourceHealth:
    attempted = succeeded + failed
    return SourceHealth(
        adapter=adapter,
        calls_attempted=attempted,
        calls_succeeded=succeeded,
        calls_failed=failed,
        failure_kinds={kind: failed} if failed else {},
        success_rate=succeeded / attempted if attempted else 0.0,
    )


def _assess(
    health: list[SourceHealth],
    *,
    posts: int = HEALTHY_POSTS,
    comments: int = HEALTHY_COMMENTS,
) -> SourceOutcome:
    return assess_source_health(
        health, posts_retrieved=posts, comments_analyzed=comments, floors=FLOORS
    ).outcome


class TestRecorder:
    def test_tallies_successes_and_failures_per_adapter(self) -> None:
        recorder = SourceHealthRecorder()
        recorder.record_success("arctic_shift")
        recorder.record_success("arctic_shift")
        recorder.record_failure("arctic_shift", kind="rate_limited")

        (health,) = recorder.snapshot()

        assert health.adapter == "arctic_shift"
        assert (health.calls_attempted, health.calls_succeeded, health.calls_failed) == (3, 2, 1)
        assert health.failure_kinds == {"rate_limited": 1}
        assert health.success_rate == pytest.approx(2 / 3)

    def test_keeps_adapters_separate_and_ordered(self) -> None:
        recorder = SourceHealthRecorder()
        recorder.record_failure("zulu")
        recorder.record_success("alpha")

        assert [entry.adapter for entry in recorder.snapshot()] == ["alpha", "zulu"]

    def test_counts_each_failure_kind(self) -> None:
        recorder = SourceHealthRecorder()
        recorder.record_failure("a", kind="timeout")
        recorder.record_failure("a", kind="timeout")
        recorder.record_failure("a", kind="http_5xx")

        assert recorder.snapshot()[0].failure_kinds == {"timeout": 2, "http_5xx": 1}

    def test_a_run_with_no_calls_records_nothing(self) -> None:
        assert SourceHealthRecorder().snapshot() == []


class TestFailureKind:
    def test_reads_the_kind_an_adapter_classified(self) -> None:
        error = TimeoutError("slow")
        error.kind = "timeout"  # type: ignore[attr-defined]

        assert failure_kind(error) == "timeout"

    def test_falls_back_to_unknown_without_losing_the_failure(self) -> None:
        assert failure_kind(RuntimeError("boom")) == UNKNOWN_FAILURE_KIND


class TestOutcomeRules:
    """The four rules in plan §8.1, each with its own test."""

    def test_rule_1_every_adapter_failing_every_call_is_unavailable(self) -> None:
        health = [_health("a", succeeded=0, failed=4), _health("b", succeeded=0, failed=2)]

        assert _assess(health) is SourceOutcome.UNAVAILABLE

    def test_rule_1_outranks_a_corpus_that_would_otherwise_look_fine(self) -> None:
        """No successful call means no evidence — no floor can rescue it."""
        health = [_health("a", succeeded=0, failed=4)]

        assert _assess(health, posts=500, comments=5000) is SourceOutcome.UNAVAILABLE

    def test_rule_2_success_rate_below_the_floor_is_degraded(self) -> None:
        health = [_health("a", succeeded=5, failed=5)]

        assessment = assess_source_health(
            health,
            posts_retrieved=HEALTHY_POSTS,
            comments_analyzed=HEALTHY_COMMENTS,
            floors=FLOORS,
        )

        assert assessment.outcome is SourceOutcome.DEGRADED
        assert assessment.aggregate_success_rate == pytest.approx(0.5)
        assert "success rate" in assessment.reasons[0]

    def test_rule_2_too_few_posts_is_degraded(self) -> None:
        health = [_health("a", succeeded=10, failed=0)]

        assert _assess(health, posts=FLOORS.min_posts_retrieved - 1) is SourceOutcome.DEGRADED

    def test_rule_2_too_few_comments_is_degraded(self) -> None:
        health = [_health("a", succeeded=10, failed=0)]

        assert (
            _assess(health, comments=FLOORS.min_comments_analyzed - 1) is SourceOutcome.DEGRADED
        )

    def test_rule_3_a_healthy_run_above_the_floors_is_healthy_however_thin_the_answer(
        self,
    ) -> None:
        """The only path §8.1 allows to say "we found 2 strong recommendations"."""
        health = [_health("a", succeeded=20, failed=0)]

        assessment = assess_source_health(
            health,
            posts_retrieved=FLOORS.min_posts_retrieved,
            comments_analyzed=FLOORS.min_comments_analyzed,
            floors=FLOORS,
        )

        assert assessment.outcome is SourceOutcome.HEALTHY
        assert assessment.reasons == []

    def test_rule_4_one_healthy_adapter_out_of_three_is_still_degraded(self) -> None:
        """A result built from one of three intended sources is degraded (plan §8.1)."""
        health = [
            _health("healthy", succeeded=10, failed=0),
            _health("down_one", succeeded=0, failed=10),
            _health("down_two", succeeded=0, failed=10),
        ]

        assessment = assess_source_health(
            health,
            posts_retrieved=HEALTHY_POSTS,
            comments_analyzed=HEALTHY_COMMENTS,
            floors=FLOORS,
        )

        assert assessment.outcome is SourceOutcome.DEGRADED
        assert assessment.aggregate_success_rate == pytest.approx(1 / 3)

    def test_rule_4_survivors_healthy_enough_in_aggregate_still_complete(self) -> None:
        health = [
            _health("a", succeeded=10, failed=0),
            _health("b", succeeded=10, failed=0),
            _health("c", succeeded=9, failed=1),
        ]

        assert _assess(health) is SourceOutcome.HEALTHY


class TestTerminalStatus:
    def test_healthy_and_unlimited_is_completed(self) -> None:
        assert (
            terminal_status(SourceOutcome.HEALTHY, budget_limited=False)
            is ResearchStatus.COMPLETED
        )

    def test_healthy_but_budget_limited_is_partial(self) -> None:
        assert (
            terminal_status(SourceOutcome.HEALTHY, budget_limited=True)
            is ResearchStatus.COMPLETED_PARTIAL
        )

    def test_degraded_outranks_partial(self) -> None:
        """Both mean incomplete, but only `partial` may claim a valid sample (§7.1)."""
        assert (
            terminal_status(SourceOutcome.DEGRADED, budget_limited=True)
            is ResearchStatus.COMPLETED_DEGRADED
        )

    def test_unavailable_is_terminal_regardless(self) -> None:
        assert (
            terminal_status(SourceOutcome.UNAVAILABLE, budget_limited=True)
            is ResearchStatus.SOURCE_UNAVAILABLE
        )
