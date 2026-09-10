"""Aggregation + Ranking (plan §4.6 steps 11-12, exact math in ``ranking/aggregation.py``).

The last step before persistence. It turns Phase 10's ``counted_opinions``
into ranked ``Result`` rows and — because nothing downstream still needs to —
settles the run's terminal status (plan §7.1): whichever of ``completed``,
``completed_partial`` or ``completed_degraded`` the run has earned, using the
source-health verdict Phase 7's :class:`SourceHealthAssessmentStep` already
recorded and the budget-limited flag any earlier step may have raised.

``source_unavailable`` never reaches here: Phase 7's health step halts the
pipeline itself the moment every adapter fails (plan §7, §8.1 rule 1), so a
run that gets this far always has *some* evidence to rank.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tripfinder.domain.models import (
    Comment,
    Entity,
    Opinion,
    ResearchFlag,
    SourceOutcome,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.health import SourceAssessment, terminal_status
from tripfinder.ranking.aggregation import aggregate_and_rank


class AggregationStep:
    """Real implementation of plan §4.6 steps 11 (Aggregation) and 12 (Ranking + Thresholds)."""

    name = "aggregation"

    def __init__(self, *, now: datetime | None = None) -> None:
        self._now = now

    async def run(self, context: PipelineContext) -> PipelineContext:
        now = self._now or datetime.now(UTC)

        counted_opinions: list[Opinion] = list(context.data.get("counted_opinions", []))
        comments: list[Comment] = list(context.data.get("comments", []))
        entities: list[Entity] = list(context.data.get("entities", []))
        config = context.research.research_config.ranking

        outcome = aggregate_and_rank(
            counted_opinions=counted_opinions,
            comments=comments,
            entities=entities,
            config=config,
            now=now,
        )

        context.research.results = outcome.strong
        context.research.weak_results = outcome.weak

        diagnostics = context.research.diagnostics
        diagnostics.record_suppression(
            step=self.name,
            reason=SuppressionReason.AGGREGATION_BELOW_RELEVANCE_THRESHOLD,
            count=outcome.opinions_below_relevance_threshold,
        )

        statistics = context.research.statistics
        statistics["respondent_pool_size"] = outcome.respondent_pool_size
        statistics["opinions_qualifying"] = outcome.qualifying_opinions
        statistics["opinions_below_relevance_threshold"] = (
            outcome.opinions_below_relevance_threshold
        )
        statistics["entities_strong"] = len(outcome.strong)
        statistics["entities_weak"] = len(outcome.weak)

        context.research.status = terminal_status(
            _source_outcome(context), budget_limited=_budget_limited(context)
        )
        return context


def _source_outcome(context: PipelineContext) -> SourceOutcome:
    """The run's source-health verdict, or ``healthy`` where nothing assessed it.

    A missing assessment only ever happens in a test exercising the metric in
    isolation — the real pipeline always runs Phase 7's health step first.
    """
    assessment: SourceAssessment | None = context.data.get("source_assessment")
    return assessment.outcome if assessment is not None else SourceOutcome.HEALTHY


def _budget_limited(context: PipelineContext) -> bool:
    return ResearchFlag.BUDGET_LIMIT_REACHED in context.research.diagnostics.flags
