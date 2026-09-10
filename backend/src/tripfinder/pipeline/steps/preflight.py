"""Source preflight (plan §8.1).

Runs before any budget or token is spent. If no registered adapter is
reachable the research terminates immediately as ``source_unavailable`` at
zero cost — discovering the outage after paying for query understanding
wastes money and delays the error the user actually needs to see.

Preflight deliberately does **not** feed the §8.1 call accounting. It is a
gate, not a sample of how well the source served this research, and folding
its one probe into the aggregate would flatter or punish the success rate
for no reason. A failed probe is still recorded as a ``SourceHealth`` entry
so the API error can name the adapter and its failure kind (§8.1 rule 1).
"""

from __future__ import annotations

import logging

from tripfinder.domain.models import ResearchStatus, SourceHealth, SourceOutcome
from tripfinder.pipeline.base import PipelineContext

logger = logging.getLogger(__name__)

UNREACHABLE = "unreachable"


class SourcePreflightStep:
    """Plan §8.1's preflight: no reachable adapter means no research."""

    name = "source_preflight"

    async def run(self, context: PipelineContext) -> PipelineContext:
        adapter = context.source
        try:
            reachable = await adapter.health_check()
        except Exception as exc:  # an unreachable source raises as readily as it returns False
            logger.warning("preflight: %s health check raised: %s", adapter.name, exc)
            reachable = False

        if reachable:
            return context

        context.research.diagnostics.source_health = [
            SourceHealth(
                adapter=adapter.name,
                calls_attempted=1,
                calls_succeeded=0,
                calls_failed=1,
                failure_kinds={UNREACHABLE: 1},
                success_rate=0.0,
            )
        ]
        context.research.diagnostics.source_outcome = SourceOutcome.UNAVAILABLE
        context.research.results = []
        context.research.status = ResearchStatus.SOURCE_UNAVAILABLE
        return context
