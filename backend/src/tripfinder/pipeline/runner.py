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
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence

from tripfinder.ai.errors import LLMProviderError
from tripfinder.domain.models import ResearchStatus, is_halting
from tripfinder.pipeline.base import PipelineContext, PipelineStep, ProgressEvent

logger = logging.getLogger(__name__)

ProgressListener = Callable[[ProgressEvent], None]
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
                self._on_progress(event)
            if is_halting(context.research.status):
                break
            if should_cancel is not None and await should_cancel():
                logger.info("pipeline: cancellation requested after %s", step.name)
                context.research.status = ResearchStatus.CANCELLED
                break
        return context


def _fail(context: PipelineContext, *, step: str, error: LLMProviderError) -> None:
    """End the run as ``failed``, naming the cause and leaving no results behind."""
    logger.warning("pipeline: %s failed on the LLM provider (%s): %s", step, error.kind, error)
    context.research.diagnostics.record_failure(kind=error.kind, step=step, detail=str(error))
    context.research.results = []
    context.research.status = ResearchStatus.FAILED
