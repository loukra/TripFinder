"""Sequential pipeline execution (plan §10 Phase 2).

A run stops as soon as it reaches a halting state (plan §7). Without that,
a research that has already terminated — rejected, awaiting clarification,
or out of reachable sources — would keep running steps and could build a
results object §7.1 says must not exist.

An LLM provider failure is caught here rather than in each AI step, for the
same reason: every AI step raises the same failures, and every one of them
must end the run the same way — ``failed``, with the cause named, and with
no results. Plan §0.1's mirror of §8.1: an unreachable model is no more a
finding than an unreachable source.

``should_cancel`` (plan §10 Phase 13) is checked between steps, the same
granularity as ``on_progress`` — a step already in flight (an LLM or source
call) always finishes before a cancellation takes effect. There is no
mechanism to interrupt a step mid-call, and pretending otherwise would risk
persisting half-written state.

The run's start is stamped here, once, because this is the only place that
knows when the pass actually began — plan §2.12.2's duration budget is
measured from it. What the run spent at the model is written back here for
the mirror-image reason: the ledger is only complete once no more steps will
run, and it has to be recorded whether the run finished, halted or failed
(plan §2.15).

Since 14.10 a run can also stop because it has nothing left to do:
``AnswerReuseStep`` may find that this question was already answered, and
sets ``context.answered`` rather than a status, because the answer it copied
is genuinely ``completed`` and the instruction to stop is not a state the
research is in (plan §2.15).

``on_progress`` is awaited, so the worker can use it to persist
``research.status`` to the database after every step — without it, a real
run only ever writes its status once, at the very end, and the UI shows
"pending" for the run's entire duration even while it is actively working.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence

from tripfinder.ai.errors import LLMProviderError
from tripfinder.domain.models import ResearchStatus, is_halting
from tripfinder.pipeline.base import PipelineContext, PipelineStep, ProgressEvent
from tripfinder.pipeline.deadline import mark_started

logger = logging.getLogger(__name__)

ProgressListener = Callable[[ProgressEvent], Awaitable[None]]
CancellationCheck = Callable[[], Awaitable[bool]]


class PipelineRunner:
    """Runs steps in order, recording a ``ProgressEvent`` after each one."""

    def __init__(
        self, steps: Sequence[PipelineStep], *, on_progress: ProgressListener | None = None
    ) -> None:
        self._steps = list(steps)
        self._on_progress = on_progress

    @property
    def steps(self) -> tuple[PipelineStep, ...]:
        return tuple(self._steps)

    async def run(
        self, context: PipelineContext, *, should_cancel: CancellationCheck | None = None
    ) -> PipelineContext:
        # The duration budget is measured from here, not from
        # ``Research.created_at``: a run resuming after clarification (plan §6)
        # must not be charged for the time a human spent answering (§2.12.2).
        mark_started(context)

        try:
            for sequence, step in enumerate(self._steps, start=1):
                try:
                    context = await step.run(context)
                except LLMProviderError as exc:
                    _fail(context, step=step.name, error=exc)
                event = ProgressEvent(
                    sequence=sequence, step_name=step.name, status=context.research.status
                )
                context.progress.append(event)
                if self._on_progress is not None:
                    await self._on_progress(event)
                if is_halting(context.research.status):
                    break
                if context.answered:
                    # Plan §2.15: this run is showing an earlier run's
                    # answer. Every step below it would spend money
                    # recomputing something already on the row.
                    logger.info("pipeline: answered from the archive after %s", step.name)
                    break
                if should_cancel is not None and await should_cancel():
                    logger.info("pipeline: cancellation requested after %s", step.name)
                    context.research.status = ResearchStatus.CANCELLED
                    break
        finally:
            # What the run spent is written whatever happened to it (plan
            # §2.15). A run that failed after forty analysis calls has spent
            # forty analysis calls, and a record that omits them would make
            # the cheapest runs look like the ones that went wrong.
            context.research.statistics.update(context.usage.totals())
        return context


def _fail(context: PipelineContext, *, step: str, error: LLMProviderError) -> None:
    """End the run as ``failed``, naming the cause and leaving no results behind."""
    logger.warning("pipeline: %s failed on the LLM provider (%s): %s", step, error.kind, error)
    context.research.diagnostics.record_failure(kind=error.kind, step=step, detail=str(error))
    context.research.results = []
    context.research.status = ResearchStatus.FAILED
