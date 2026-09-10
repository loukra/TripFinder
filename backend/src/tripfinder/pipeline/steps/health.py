"""Source health assessment (plan §8.1).

Applies §8.1's outcome rules to the run's call accounting, immediately
after retrieval and pre-filtering — before the expensive analysis steps,
and early enough that a total outage stops the pipeline rather than
producing a results object that must not exist.

The step decides *whether the corpus can be trusted*; it does not decide
the terminal status of a run that is still going. ``unavailable`` is
terminal here and halts the pipeline (plan §7). ``degraded`` is recorded on
the research and converted to a terminal status by
``pipeline.health.terminal_status`` when the run finishes, so a degraded
run can never be reported in the same words as a healthy one (plan §7.1).
"""

from __future__ import annotations

from tripfinder.domain.models import ResearchStatus, SourceOutcome
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.health import assess_source_health, get_recorder


class SourceHealthAssessmentStep:
    """Real implementation of plan §8.1's outcome rules."""

    name = "source_health_assessment"

    async def run(self, context: PipelineContext) -> PipelineContext:
        diagnostics = context.research.diagnostics
        health = get_recorder(context).snapshot()

        assessment = assess_source_health(
            health,
            posts_retrieved=int(context.data.get("posts_retrieved", 0)),
            comments_analyzed=len(context.data.get("analysis_comments", [])),
            floors=context.research.research_config.source_health_floors,
        )

        diagnostics.source_health = health
        diagnostics.source_outcome = assessment.outcome
        context.data["source_assessment"] = assessment

        if assessment.outcome is SourceOutcome.UNAVAILABLE:
            # §8.1 rule 1: no evidence at all means no results object.
            context.research.results = []
            context.research.status = ResearchStatus.SOURCE_UNAVAILABLE

        return context
