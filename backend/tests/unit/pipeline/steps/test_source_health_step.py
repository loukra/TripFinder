"""The §8.1 outcome rules as a pipeline step, and what each outcome does to the run."""

from __future__ import annotations

from builders.phase7 import make_comment, make_context
from tripfinder.domain.config import ResearchConfig, SourceHealthFloors
from tripfinder.domain.models import (
    ResearchStatus,
    Result,
    SourceOutcome,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.health import get_recorder, terminal_status
from tripfinder.pipeline.steps.health import SourceHealthAssessmentStep

FLOORS = SourceHealthFloors()


def _run_context(
    *, succeeded: int, failed: int, posts: int, comments: int
) -> PipelineContext:
    context = make_context(config=ResearchConfig(source_health_floors=FLOORS))
    recorder = get_recorder(context)
    for _ in range(succeeded):
        recorder.record_success("recording")
    for _ in range(failed):
        recorder.record_failure("recording", kind="http_5xx")
    context.data["posts_retrieved"] = posts
    context.data["analysis_comments"] = [
        make_comment(f"c{index}") for index in range(comments)
    ]
    return context


def _healthy_context() -> PipelineContext:
    return _run_context(
        succeeded=20,
        failed=0,
        posts=FLOORS.min_posts_retrieved,
        comments=FLOORS.min_comments_analyzed,
    )


async def test_a_healthy_run_is_left_to_continue() -> None:
    context = _healthy_context()
    context.research.status = ResearchStatus.ANALYZING

    await SourceHealthAssessmentStep().run(context)

    assert context.research.diagnostics.source_outcome is SourceOutcome.HEALTHY
    assert context.research.status is ResearchStatus.ANALYZING


async def test_a_degraded_run_continues_but_is_marked() -> None:
    """Results are computed and stored; the API marks them untrusted (§8.1 rule 2)."""
    context = _run_context(
        succeeded=5, failed=5, posts=20, comments=FLOORS.min_comments_analyzed
    )
    context.research.status = ResearchStatus.ANALYZING

    await SourceHealthAssessmentStep().run(context)

    assert context.research.diagnostics.source_outcome is SourceOutcome.DEGRADED
    assert context.research.status is ResearchStatus.ANALYZING


async def test_a_total_outage_terminates_the_run_with_no_results() -> None:
    context = _run_context(succeeded=0, failed=6, posts=0, comments=0)
    context.research.results = [
        Result(
            entity_id="alaska",
            entity_name="Alaska",
            supporter_count=3,
            share=0.5,
            respondent_pool_size=6,
            discussion_count=2,
            weighted_score=3.0,
            confidence=1.0,
        )
    ]

    await SourceHealthAssessmentStep().run(context)

    assert context.research.status is ResearchStatus.SOURCE_UNAVAILABLE
    assert context.research.results == []


async def test_the_per_adapter_accounting_is_persisted_on_the_research() -> None:
    context = _run_context(
        succeeded=9, failed=1, posts=20, comments=FLOORS.min_comments_analyzed
    )

    await SourceHealthAssessmentStep().run(context)

    (health,) = context.research.diagnostics.source_health
    assert health.calls_attempted == 10
    assert health.failure_kinds == {"http_5xx": 1}


async def test_the_degrading_reason_is_recorded_for_the_user_to_read() -> None:
    context = _run_context(succeeded=10, failed=0, posts=1, comments=5)

    await SourceHealthAssessmentStep().run(context)

    assessment = context.data["source_assessment"]
    assert assessment.outcome is SourceOutcome.DEGRADED
    assert any("posts" in reason for reason in assessment.reasons)
    assert any("comments" in reason for reason in assessment.reasons)


async def test_a_healthy_run_with_a_thin_corpus_is_not_degraded() -> None:
    """§8.1 rule 3 — the only path that may report an honest thin finding."""
    context = _healthy_context()

    await SourceHealthAssessmentStep().run(context)

    assert context.research.diagnostics.source_outcome is SourceOutcome.HEALTHY
    assert context.data["source_assessment"].reasons == []


class TestTheFourOutcomeRulesEndToEnd:
    """Each §8.1 rule from recorded calls all the way to a §7.1 terminal state."""

    async def _terminal(
        self, context: PipelineContext, *, budget_limited: bool = False
    ) -> ResearchStatus:
        await SourceHealthAssessmentStep().run(context)
        outcome = context.research.diagnostics.source_outcome
        assert outcome is not None
        return terminal_status(outcome, budget_limited=budget_limited)

    async def test_rule_1_a_total_outage_ends_as_source_unavailable(self) -> None:
        context = _run_context(succeeded=0, failed=8, posts=0, comments=0)

        assert await self._terminal(context) is ResearchStatus.SOURCE_UNAVAILABLE
        assert context.research.results == []

    async def test_rule_2_a_fifty_percent_failure_rate_ends_as_completed_degraded(self) -> None:
        context = _run_context(
            succeeded=5, failed=5, posts=20, comments=FLOORS.min_comments_analyzed
        )

        assert await self._terminal(context) is ResearchStatus.COMPLETED_DEGRADED

    async def test_rule_3_a_healthy_run_with_little_to_say_ends_as_completed(self) -> None:
        assert await self._terminal(_healthy_context()) is ResearchStatus.COMPLETED

    async def test_rule_3_a_healthy_run_stopped_by_budget_ends_as_completed_partial(self) -> None:
        context = _healthy_context()

        assert (
            await self._terminal(context, budget_limited=True)
            is ResearchStatus.COMPLETED_PARTIAL
        )

    async def test_rule_4_one_of_three_adapters_healthy_ends_as_completed_degraded(self) -> None:
        context = make_context(config=ResearchConfig(source_health_floors=FLOORS))
        recorder = get_recorder(context)
        for _ in range(10):
            recorder.record_success("up")
            recorder.record_failure("down_one", kind="timeout")
            recorder.record_failure("down_two", kind="timeout")
        context.data["posts_retrieved"] = 20
        context.data["analysis_comments"] = [
            make_comment(f"c{index}") for index in range(FLOORS.min_comments_analyzed)
        ]

        assert await self._terminal(context) is ResearchStatus.COMPLETED_DEGRADED
        assert len(context.research.diagnostics.source_health) == 3
