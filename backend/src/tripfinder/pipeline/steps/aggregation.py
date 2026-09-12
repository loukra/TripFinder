"""Aggregation + Ranking (plan §4.6 steps 11-12, exact math in ``ranking/aggregation.py``).

Turns Phase 10's ``counted_opinions`` into ranked ``Result`` rows and
decides the run's terminal status (plan §7.1): whichever of ``completed``,
``completed_partial`` or ``completed_degraded`` the run has earned, using the
source-health verdict Phase 7's :class:`SourceHealthAssessmentStep` already
recorded and the budget-limited flag any earlier step may have raised.

**Decides it, but does not apply it.** The verdict is parked in
``context.data["terminal_status"]`` and Summarization — the actual last step
— puts it on the research. This step used to set it directly, from a time
when it really was last; once Summarization moved in behind it, that made
every run publish a terminal status one step early, with a complete ranking
and no explanations under it.

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

        # Decided here, applied by the last step. §7.1's logic belongs to
        # this step — it is the one that knows the outcome — but a terminal
        # status is a promise that the record is complete, and Summarization
        # has not run yet. The worker saves after every step, so setting it
        # here published a finished-looking run whose results carried no
        # explanations for as long as the summarization call took. A client
        # that stops polling on a terminal status (every client does) read
        # exactly that record and never looked again: a ranking with no
        # reasons under it, indistinguishable from one whose explanations
        # were thrown away.
        context.data["terminal_status"] = terminal_status(
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
