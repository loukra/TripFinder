"""Source health accounting and the §8.1 outcome rules.

This module is the mechanical half of plan §0.1: it is what lets a run that
*could not see* be told apart from a run that *saw little*. It records every
source call attempt per adapter, then applies §8.1's four outcome rules to
the totals.

The rules are written for **N adapters**, and since plan §2.11 a run really
does have two: the web search provider that finds thread addresses and the
source adapter that retrieves them. Each is recorded under its own name.
Adding a third changes the count the rules are applied to, never the rules
themselves — which is why rule 4 ("some up, some down") needs no branch of
its own: an adapter that failed every call drags the aggregate success rate
under the floor, and rule 2 catches it.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from tripfinder.domain.config import SourceHealthFloors
from tripfinder.domain.models import ResearchStatus, SourceHealth, SourceOutcome
from tripfinder.pipeline.base import PipelineContext
from tripfinder.sources.failures import UNKNOWN_FAILURE_KIND

_RECORDER_KEY = "source_health_recorder"


class SourceHealthRecorder:
    """Tallies source call outcomes per adapter for one research run."""

    def __init__(self) -> None:
        self._attempted: dict[str, int] = defaultdict(int)
        self._succeeded: dict[str, int] = defaultdict(int)
        self._failure_kinds: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record_success(self, adapter: str) -> None:
        self._attempted[adapter] += 1
        self._succeeded[adapter] += 1

    def record_failure(self, adapter: str, *, kind: str = UNKNOWN_FAILURE_KIND) -> None:
        self._attempted[adapter] += 1
        self._failure_kinds[adapter][kind] += 1

    def snapshot(self) -> list[SourceHealth]:
        """The per-adapter accounting, adapter name ascending."""
        health: list[SourceHealth] = []
        for adapter in sorted(self._attempted):
            attempted = self._attempted[adapter]
            succeeded = self._succeeded[adapter]
            health.append(
                SourceHealth(
                    adapter=adapter,
                    calls_attempted=attempted,
                    calls_succeeded=succeeded,
                    calls_failed=attempted - succeeded,
                    failure_kinds=dict(self._failure_kinds.get(adapter, {})),
                    success_rate=succeeded / attempted if attempted else 0.0,
                )
            )
        return health


def get_recorder(context: PipelineContext) -> SourceHealthRecorder:
    """The run's recorder, created on first use.

    Every step that calls a source shares one recorder, so the aggregate
    §8.1 evaluates covers discovery searches and retrieval alike.
    """
    recorder = context.data.get(_RECORDER_KEY)
    if not isinstance(recorder, SourceHealthRecorder):
        recorder = SourceHealthRecorder()
        context.data[_RECORDER_KEY] = recorder
    return recorder


class SourceAssessment(BaseModel):
    """The §8.1 outcome rules' verdict, with the reasons that produced it."""

    outcome: SourceOutcome
    reasons: list[str] = Field(default_factory=list)
    aggregate_success_rate: float = Field(ge=0.0, le=1.0)
    posts_retrieved: int = Field(ge=0)
    comments_analyzed: int = Field(ge=0)


def assess_source_health(
    health: list[SourceHealth],
    *,
    posts_retrieved: int,
    comments_analyzed: int,
    floors: SourceHealthFloors,
) -> SourceAssessment:
    """Apply §8.1's outcome rules to one run's accounting.

    Rule 1 (every adapter failed every call) is checked first and is
    absolute: a run with no successful call anywhere has no evidence, and no
    floor comparison can rescue it into a reportable result.
    """
    attempted = sum(entry.calls_attempted for entry in health)
    succeeded = sum(entry.calls_succeeded for entry in health)
    aggregate_success_rate = succeeded / attempted if attempted else 0.0

    if attempted > 0 and succeeded == 0:
        adapters = ", ".join(entry.adapter for entry in health)
        return SourceAssessment(
            outcome=SourceOutcome.UNAVAILABLE,
            reasons=[f"every source call failed ({adapters})"],
            aggregate_success_rate=0.0,
            posts_retrieved=posts_retrieved,
            comments_analyzed=comments_analyzed,
        )

    reasons: list[str] = []
    if attempted > 0 and aggregate_success_rate < floors.min_source_success_rate:
        reasons.append(
            f"source success rate {aggregate_success_rate:.0%} is below the "
            f"{floors.min_source_success_rate:.0%} floor"
        )
    if posts_retrieved < floors.min_posts_retrieved:
        reasons.append(
            f"only {posts_retrieved} posts were retrieved, below the floor of "
            f"{floors.min_posts_retrieved}"
        )
    if comments_analyzed < floors.min_comments_analyzed:
        reasons.append(
            f"only {comments_analyzed} comments reached analysis, below the floor of "
            f"{floors.min_comments_analyzed}"
        )

    return SourceAssessment(
        outcome=SourceOutcome.DEGRADED if reasons else SourceOutcome.HEALTHY,
        reasons=reasons,
        aggregate_success_rate=aggregate_success_rate,
        posts_retrieved=posts_retrieved,
        comments_analyzed=comments_analyzed,
    )


def terminal_status(outcome: SourceOutcome, *, budget_limited: bool) -> ResearchStatus:
    """The §7.1 terminal state a finished run lands in.

    ``degraded`` outranks ``partial`` deliberately. Both mean "incomplete",
    but they promise different things: `completed_partial` says the evidence
    gathered is a valid sample that we stopped collecting on purpose, and a
    degraded run cannot make that promise about anything.
    """
    if outcome is SourceOutcome.UNAVAILABLE:
        return ResearchStatus.SOURCE_UNAVAILABLE
    if outcome is SourceOutcome.DEGRADED:
        return ResearchStatus.COMPLETED_DEGRADED
    if budget_limited:
        return ResearchStatus.COMPLETED_PARTIAL
    return ResearchStatus.COMPLETED
