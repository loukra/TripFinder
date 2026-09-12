"""Pipeline step protocol, execution context, and progress reporting.

Steps live outside ``domain/``, so this module is free to import the ports
directly (plan §3.1). ``PipelineContext.data`` is a step-to-step scratch
space: each step reads the keys it needs and writes the keys later steps
need, so the context itself never has to know about business concepts
(documents, comments, opinions...) owned by steps not yet implemented.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from tripfinder.domain.models import Research, ResearchStatus, Result
from tripfinder.domain.ports import (
    AnswerArchive,
    LLMProvider,
    SourceAdapter,
    WebSearchProvider,
)
from tripfinder.domain.usage import TokenLedger


class ProgressEvent(BaseModel):
    """One step's completion, in run order (plan §10 Phase 2 acceptance)."""

    sequence: int
    step_name: str
    status: ResearchStatus


@dataclass(frozen=True)
class PartialResults:
    """One provisional ranking, computed mid-run (plan §2.13).

    Display state, and nothing else. ``batches_completed`` is how many
    analysis batches it covers: because batches finish in an order the run
    does not control, a listener must refuse anything that does not advance
    it, or the counts on screen can go backwards (§2.13.2) — the one thing
    that would make a provisional answer unsafe to show.
    """

    results: list[Result]
    """Strong recommendations so far — §4.4's threshold, never padded."""

    weak_results: list[Result]
    """Everything else ranked so far. Early on this is where the evidence is."""

    batches_completed: int
    comments_analysed: int


PartialResultsListener = Callable[[PartialResults], Awaitable[None]]
"""Called with each new snapshot, in the order they were computed."""


@dataclass
class PipelineContext:
    """Mutable state threaded through pipeline steps for one research run."""

    research: Research
    source: SourceAdapter
    search: WebSearchProvider
    llm: LLMProvider
    archive: AnswerArchive | None = None
    """Earlier answers this run may reuse (plan §2.15). Unset, it never reuses.

    Optional because most callers have no database — the pipeline has never
    had one and does not get one here. A run without an archive behaves
    exactly as every run did before 14.10: it does the work itself."""
    usage: TokenLedger = field(default_factory=TokenLedger)
    """What this run spent at the model (plan §2.15).

    Lives on the context rather than inside the provider because the run is
    what the number describes, and because the runner writes it into
    ``statistics`` whatever the run's outcome was — a failed run that spent
    four calls has spent them."""
    answered: bool = False
    """Set by ``AnswerReuseStep`` when this run's answer is already final.

    Not a status, deliberately. ``completed`` is set mid-pipeline by the
    source health step and several steps legitimately run after it, so it
    cannot mean "stop"; and a reused answer must be ``completed`` and
    nothing else, because it is a genuinely finished answer — an older one,
    which ``Research.reused`` is what says. So the instruction to stop is
    carried here, where it says only what it means."""
    data: dict[str, Any] = field(default_factory=dict)
    progress: list[ProgressEvent] = field(default_factory=list)
    on_partial_results: PartialResultsListener | None = None
    """Where provisional rankings go while a run is still analysing (plan §2.13).

    A sibling of ``progress`` rather than something the steps write into the
    context: a snapshot is not part of the run's record, and giving it a
    resting place next to the data later steps read would invite exactly the
    derivation §2.13.2 forbids. Unset — in tests, and in any caller that has
    nowhere to put a snapshot — the run behaves as it did before.
    """


@runtime_checkable
class PipelineStep(Protocol):
    """One stage of the research pipeline (plan §4.6)."""

    name: str

    async def run(self, context: PipelineContext) -> PipelineContext: ...
