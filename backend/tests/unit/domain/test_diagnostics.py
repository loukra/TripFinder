"""Research diagnostics — the evidence trail plan §0.1 requires."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tripfinder.domain.models import (
    HALTING_STATUSES,
    EntityResolutionMethod,
    EntityResolutionOutcome,
    EntityType,
    Research,
    ResearchDiagnostics,
    ResearchFlag,
    ResearchStatus,
    SourceHealth,
    SuppressionReason,
    TriageDecidedBy,
    TriageDecision,
    TriageVerdict,
    is_halting,
)


def test_a_new_research_starts_with_empty_diagnostics() -> None:
    research = Research(
        original_query="underrated states",
        created_at=datetime.now(UTC),
        status=ResearchStatus.PENDING,
    )

    assert research.diagnostics == ResearchDiagnostics()


def test_diagnostics_round_trip_through_serialization() -> None:
    diagnostics = ResearchDiagnostics(
        source_health=[
            SourceHealth(
                adapter="arctic_shift",
                calls_attempted=4,
                calls_succeeded=3,
                calls_failed=1,
                failure_kinds={"timeout": 1},
                success_rate=0.75,
            )
        ],
        triage_decisions=[
            TriageDecision(
                document_id="d1",
                verdict=TriageVerdict.TOPICAL,
                reason="title names Alaska",
                confidence=1.0,
                decided_by=TriageDecidedBy.RULE,
            )
        ],
        entity_resolutions=[
            EntityResolutionOutcome(
                surface_form="the Last Frontier",
                entity_type=EntityType.STATE,
                occurrences=3,
                entity_id="state:alaska",
                canonical_name="Alaska",
                decided_by=EntityResolutionMethod.RULE,
                confidence=1.0,
                reason="a known name for Alaska",
            )
        ],
        flags=[ResearchFlag.LOW_POLLING_DOCUMENT_RATIO],
    )
    diagnostics.record_suppression(
        step="document_triage", reason=SuppressionReason.TRIAGE_EXCLUDED, count=2
    )

    assert ResearchDiagnostics.model_validate(diagnostics.model_dump(mode="json")) == diagnostics


class TestSuppressionRecording:
    def test_repeats_of_the_same_reason_coalesce(self) -> None:
        diagnostics = ResearchDiagnostics()

        diagnostics.record_suppression(
            step="cheap_prefilter", reason=SuppressionReason.PREFILTER_TOO_SHORT, count=1
        )
        diagnostics.record_suppression(
            step="cheap_prefilter", reason=SuppressionReason.PREFILTER_TOO_SHORT, count=3
        )

        (suppression,) = diagnostics.suppressions
        assert suppression.count == 4

    def test_different_details_stay_separate(self) -> None:
        diagnostics = ResearchDiagnostics()

        diagnostics.record_suppression(
            step="content_retrieval",
            reason=SuppressionReason.RETRIEVAL_SOURCE_FAILURE,
            count=1,
            detail="timeout",
        )
        diagnostics.record_suppression(
            step="content_retrieval",
            reason=SuppressionReason.RETRIEVAL_SOURCE_FAILURE,
            count=1,
            detail="http_5xx",
        )

        assert [entry.detail for entry in diagnostics.suppressions] == ["timeout", "http_5xx"]

    def test_a_zero_count_records_nothing(self) -> None:
        diagnostics = ResearchDiagnostics()

        diagnostics.record_suppression(
            step="cheap_prefilter", reason=SuppressionReason.PREFILTER_TOO_SHORT, count=0
        )

        assert diagnostics.suppressions == []


class TestFlags:
    def test_a_flag_is_raised_once(self) -> None:
        diagnostics = ResearchDiagnostics()

        diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)
        diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)

        assert diagnostics.flags == [ResearchFlag.BUDGET_LIMIT_REACHED]


class TestEntityResolutionValidation:
    def _outcome(self, **overrides: object) -> EntityResolutionOutcome:
        payload: dict[str, object] = {
            "surface_form": "that one state",
            "entity_type": "state",
            "occurrences": 4,
            "decided_by": "ai",
            "confidence": 0.2,
            "reason": "the quote does not say which state is meant",
        }
        payload.update(overrides)
        return EntityResolutionOutcome.model_validate(payload)

    def test_an_unresolved_form_carries_no_entity(self) -> None:
        """`PROJECT.md` §15's refusal, as data: a name and no merge."""
        outcome = self._outcome()

        assert outcome.entity_id is None
        assert outcome.canonical_name is None

    def test_a_form_nobody_wrote_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._outcome(occurrences=0)

    def test_an_outcome_without_a_reason_is_rejected(self) -> None:
        """A refusal without a reason is exactly the silence plan §0.1 forbids."""
        with pytest.raises(ValidationError):
            self._outcome(reason="")


class TestSourceHealthValidation:
    def test_a_success_rate_above_one_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourceHealth(
                adapter="a",
                calls_attempted=1,
                calls_succeeded=1,
                calls_failed=0,
                success_rate=1.5,
            )

    def test_an_unnamed_adapter_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourceHealth(
                adapter="",
                calls_attempted=1,
                calls_succeeded=1,
                calls_failed=0,
                success_rate=1.0,
            )


class TestHaltingStatuses:
    @pytest.mark.parametrize("status", sorted(HALTING_STATUSES))
    def test_terminal_and_waiting_states_halt(self, status: ResearchStatus) -> None:
        assert is_halting(status) is True

    @pytest.mark.parametrize(
        "status",
        [
            ResearchStatus.PENDING,
            ResearchStatus.DISCOVERING,
            ResearchStatus.RETRIEVING,
            ResearchStatus.ANALYZING,
            ResearchStatus.COMPLETED,
            ResearchStatus.COMPLETED_PARTIAL,
            ResearchStatus.COMPLETED_DEGRADED,
        ],
    )
    def test_running_and_reportable_states_do_not_halt(self, status: ResearchStatus) -> None:
        assert is_halting(status) is False
