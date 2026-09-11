"""Pipeline step protocol, execution context, and progress reporting.

Steps live outside ``domain/``, so this module is free to import the ports
directly (plan §3.1). ``PipelineContext.data`` is a step-to-step scratch
space: each step reads the keys it needs and writes the keys later steps
need, so the context itself never has to know about business concepts
(documents, comments, opinions...) owned by steps not yet implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from tripfinder.domain.models import Research, ResearchStatus
from tripfinder.domain.ports import LLMProvider, SourceAdapter, WebSearchProvider


class ProgressEvent(BaseModel):
    """One step's completion, in run order (plan §10 Phase 2 acceptance)."""

    sequence: int
    step_name: str
    status: ResearchStatus


@dataclass
class PipelineContext:
    """Mutable state threaded through pipeline steps for one research run."""

    research: Research
    source: SourceAdapter
    search: WebSearchProvider
    llm: LLMProvider
    data: dict[str, Any] = field(default_factory=dict)
    progress: list[ProgressEvent] = field(default_factory=list)


@runtime_checkable
class PipelineStep(Protocol):
    """One stage of the research pipeline (plan §4.6)."""

    name: str

    async def run(self, context: PipelineContext) -> PipelineContext: ...
