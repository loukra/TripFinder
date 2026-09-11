"""The research duration budget, as an admission gate (plan §2.12.2).

``maxResearchDuration`` went unread until 14.6e: the measured run finished in
2408 s against a 300 s budget and nothing noticed. This module is what reads
it, and the shape of the rule matters as much as the number.

**The limit stops admission, never completion.** A deadline that cancels work
in flight throws away tokens already paid for and gets nothing back for them
— the request was billed the moment it was sent, so abandoning the response
buys no saving, only a smaller sample. What the limit governs is therefore
what may still be *started*.

Because in-flight work always finishes, the deadline alone would overrun the
budget by up to one call. So the dispatch deadline is *derived* from the
promise rather than equal to it: ``started_at + maxResearchDuration −
tailReserve``. The other way round — deadline at 300 s, tail on top — would
make a user's five minutes mean seven.

**Started when?** At the start of this pipeline pass, not at
``Research.created_at``. A research that paused for clarification (plan §6)
may resume hours later, and charging it for the time a human spent thinking
would have it arrive at analysis with the budget already spent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tripfinder.pipeline.base import PipelineContext

_STARTED_AT_KEY = "run_started_at"


def mark_started(context: PipelineContext, *, now: datetime | None = None) -> datetime:
    """Stamp the start of this pipeline pass, once. Later calls return the first."""
    existing = context.data.get(_STARTED_AT_KEY)
    if isinstance(existing, datetime):
        return existing
    started = now or datetime.now(UTC)
    context.data[_STARTED_AT_KEY] = started
    return started


def admission_deadline(context: PipelineContext, *, now: datetime | None = None) -> datetime:
    """After this instant, no further expensive work may be dispatched.

    Falls back to stamping the start now when nothing did — which happens
    only in a test exercising one step alone; the runner always stamps first.
    """
    budget = context.research.research_config.budget
    started = mark_started(context, now=now)
    return started + timedelta(
        seconds=budget.max_research_duration_seconds - budget.tail_reserve_seconds
    )
