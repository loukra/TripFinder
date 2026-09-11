"""A provisional ranking from the comments analysed so far (plan §2.13).

A research run reports once, at the end, because nothing downstream of
analysis runs until analysis is finished. But steps 8-11 — entity
resolution, deduplication, aggregation, ranking — are cheap and almost
entirely deterministic, so running them again over a *partial* corpus costs
a fraction of a second and no model call at all. That is what this module
does, and it is the whole of plan §2.13's mechanism.

**There is no second implementation of the metric.** A snapshot is the same
three steps the run itself will use, against a throwaway copy of the
context. If the numbers could drift apart, the feature would be a second
answer to the question the product exists to answer — so they are not
allowed to be two pieces of code (``tests/unit/pipeline/test_snapshot.py``
proves they are one).

Three things make the copy safe, and each of them is load-bearing:

**Aggregation settles the run's terminal status.** ``AggregationStep`` ends
with ``research.status = terminal_status(...)`` — ``completed``,
``completed_partial`` or ``completed_degraded``. On a throwaway copy that is
harmless; copied back it would have a run announce itself finished sixty
seconds in. So only ``results`` and ``weak_results`` are ever read off the
copy, and everything else it wrote — statuses, statistics, suppressions —
is discarded with it.

**The model is never asked.** Entity resolution runs in its deterministic
mode (``ask_model=False``): the catalogue and text normalisation still
resolve most names for free, and a name they cannot place is simply not
counted. A snapshot therefore *under*-reports rather than over-reports,
which is the safe direction, and it stays free enough to run after every
batch.

**Three context keys, seeded together.** Entity resolution reads
``counted_analyses`` and ``evidence_analyses``; deduplication reads
``comment_analyses``. The analysis step sets all three at the end of its
run; a snapshot seeds all three from the same partial corpus. Seeding one
and not the others would have resolution see comments deduplication does
not, and the result would be a silently wrong count with nothing to flag it.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import replace

from tripfinder.analysis.comment_analysis import CommentAnalysis
from tripfinder.domain.models import Result
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.aggregation import AggregationStep
from tripfinder.pipeline.steps.entity_resolution import EntityResolutionStep
from tripfinder.pipeline.steps.user_deduplication import UserDeduplicationStep


async def snapshot(
    context: PipelineContext,
    *,
    counted_analyses: Sequence[CommentAnalysis],
    evidence_analyses: Sequence[CommentAnalysis],
) -> tuple[list[Result], list[Result]]:
    """Rank what has been analysed so far. Returns ``(strong, weak)``.

    ``context`` is left exactly as it was found — the steps run against a
    copy — so a caller may snapshot as often as it likes without touching
    the run's own state.
    """
    scratch = _scratch(context)
    scratch.data["counted_analyses"] = list(counted_analyses)
    scratch.data["evidence_analyses"] = list(evidence_analyses)
    scratch.data["comment_analyses"] = [*counted_analyses, *evidence_analyses]

    for step in (
        EntityResolutionStep(ask_model=False),
        UserDeduplicationStep(),
        AggregationStep(),
    ):
        scratch = await step.run(scratch)

    # Only these two. Everything else the copy holds — a terminal status
    # above all — stays on the copy (plan §2.13.2).
    return list(scratch.research.results), list(scratch.research.weak_results)


def _scratch(context: PipelineContext) -> PipelineContext:
    """A context the snapshot steps may write to freely.

    ``research`` is deep-copied because aggregation writes to it. ``data``
    is copied one level: the steps add keys rather than mutating the values
    already there, and the values themselves — the plan, the comments, the
    health recorder — are read-only to all three, so copying them as well
    would cost a corpus-sized copy per snapshot to protect nothing.

    The adapters are shared deliberately. None of these steps calls one, and
    a snapshot that reached an adapter would be a cost the run did not
    budget for.
    """
    return replace(
        context,
        research=context.research.model_copy(deep=True),
        data=copy.copy(context.data),
        progress=list(context.progress),
        on_partial_results=None,
    )
