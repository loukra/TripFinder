"""Aggregation + Ranking as a pipeline step (plan §4.6 steps 11-12).

The math itself is covered exhaustively in ``tests/unit/ranking/
test_aggregation_math.py``; this file only checks the wiring — that the step
reads the right context keys, writes ``results``/``weak_results``, records
the relevance suppression, and settles the run's terminal status using
whatever Phase 7's health step left behind.
"""

from __future__ import annotations

from builders.phase7 import make_comment, make_context
from tripfinder.domain.config import RankingConfig, ResearchConfig
from tripfinder.domain.models import (
    Entity,
    EntityType,
    Opinion,
    ResearchFlag,
    ResearchStatus,
    SourceOutcome,
    Stance,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.health import SourceAssessment
from tripfinder.pipeline.steps.aggregation import AggregationStep

ALASKA = Entity(canonical_id="state:alaska", canonical_name="Alaska", entity_type=EntityType.STATE)


def _opinion(comment_id: str, user_id: str, *, relevance: float = 0.8) -> Opinion:
    return Opinion(
        comment_id=comment_id,
        user_id=user_id,
        entity_id=ALASKA.canonical_id,
        stance=Stance.POSITIVE,
        strength=0.8,
        relevance=relevance,
        timestamp=make_comment(comment_id).created_at,
        confidence=0.8,
    )


def _context(
    *, opinions: list[Opinion] | None = None, config: ResearchConfig | None = None
) -> PipelineContext:
    opinions = opinions if opinions is not None else [_opinion("c1", "u1")]
    context = make_context(
        config=config or ResearchConfig(ranking=RankingConfig(minimum_independent_users=1))
    )
    context.data["counted_opinions"] = opinions
    context.data["comments"] = [make_comment(o.comment_id, user_id=o.user_id) for o in opinions]
    context.data["entities"] = [ALASKA]
    return context


def _assessment(outcome: SourceOutcome) -> SourceAssessment:
    return SourceAssessment(
        outcome=outcome,
        aggregate_success_rate=1.0 if outcome is SourceOutcome.HEALTHY else 0.5,
        posts_retrieved=20,
        comments_analyzed=200,
    )


class TestComputesResults:
    async def test_writes_strong_results_from_counted_opinions(self) -> None:
        context = _context()

        await AggregationStep().run(context)

        [result] = context.research.results
        assert result.entity_id == "state:alaska"
        assert result.supporter_count == 1
        assert context.research.weak_results == []

    async def test_below_threshold_entities_land_in_weak_results(self) -> None:
        context = _context(config=ResearchConfig())  # default minimum_independent_users=5

        await AggregationStep().run(context)

        assert context.research.results == []
        [weak] = context.research.weak_results
        assert weak.entity_id == "state:alaska"

    async def test_statistics_are_recorded(self) -> None:
        context = _context()

        await AggregationStep().run(context)

        assert context.research.statistics["respondent_pool_size"] == 1
        assert context.research.statistics["entities_strong"] == 1
        assert context.research.statistics["entities_weak"] == 0


class TestRelevanceSuppression:
    async def test_below_threshold_opinions_are_recorded_as_suppressed(self) -> None:
        config = ResearchConfig(
            ranking=RankingConfig(minimum_independent_users=1, relevance_threshold=0.5)
        )
        context = _context(opinions=[_opinion("c1", "u1", relevance=0.1)], config=config)

        await AggregationStep().run(context)

        [suppression] = context.research.diagnostics.suppressions
        assert suppression.reason is SuppressionReason.AGGREGATION_BELOW_RELEVANCE_THRESHOLD
        assert suppression.count == 1

    async def test_no_suppression_recorded_when_nothing_is_dropped(self) -> None:
        context = _context()

        await AggregationStep().run(context)

        assert context.research.diagnostics.suppressions == []


class TestTerminalStatus:
    async def test_defaults_to_completed_when_no_health_assessment_is_present(self) -> None:
        context = _context()

        await AggregationStep().run(context)

        assert context.research.status is ResearchStatus.COMPLETED

    async def test_a_healthy_assessment_yields_completed(self) -> None:
        context = _context()
        context.data["source_assessment"] = _assessment(SourceOutcome.HEALTHY)

        await AggregationStep().run(context)

        assert context.research.status is ResearchStatus.COMPLETED

    async def test_a_degraded_assessment_yields_completed_degraded(self) -> None:
        context = _context()
        context.data["source_assessment"] = _assessment(SourceOutcome.DEGRADED)

        await AggregationStep().run(context)

        assert context.research.status is ResearchStatus.COMPLETED_DEGRADED

    async def test_a_budget_limited_flag_yields_completed_partial(self) -> None:
        context = _context()
        context.research.diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)

        await AggregationStep().run(context)

        assert context.research.status is ResearchStatus.COMPLETED_PARTIAL

    async def test_degraded_outranks_budget_limited(self) -> None:
        context = _context()
        context.data["source_assessment"] = _assessment(SourceOutcome.DEGRADED)
        context.research.diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)

        await AggregationStep().run(context)

        assert context.research.status is ResearchStatus.COMPLETED_DEGRADED
