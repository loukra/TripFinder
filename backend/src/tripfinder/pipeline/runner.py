"""Sequential pipeline execution (plan §10 Phase 2)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from tripfinder.pipeline.base import PipelineContext, PipelineStep, ProgressEvent

ProgressListener = Callable[[ProgressEvent], None]


class PipelineRunner:
    """Runs steps in order, recording a ``ProgressEvent`` after each one."""

    def __init__(
        self, steps: Sequence[PipelineStep], *, on_progress: ProgressListener | None = None
    ) -> None:
        self._steps = list(steps)
        self._on_progress = on_progress

    async def run(self, context: PipelineContext) -> PipelineContext:
        for sequence, step in enumerate(self._steps, start=1):
            context = await step.run(context)
            event = ProgressEvent(
                sequence=sequence, step_name=step.name, status=context.research.status
            )
            context.progress.append(event)
            if self._on_progress is not None:
                self._on_progress(event)
        return context
