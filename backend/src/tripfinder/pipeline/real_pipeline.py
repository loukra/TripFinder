"""Assembles the real pipeline: production steps, Arctic Shift, OpenAI/fake (plan §10 Phase 13).

Plan §2.9 named this gap directly: the worker always ran
``build_fake_pipeline_runner()``, regardless of what ``LLM_PROVIDER`` said,
because no phase ever built the real counterpart. This module is that
counterpart — the one place a process decides which adapters a research
actually runs against.

Two runners, not one. A research that paused for clarification (plan §6)
already spent its Preflight and Query Understanding steps before it halted;
resuming it must not repeat them; ``build_resumed_pipeline_runner`` picks up
at Discovery with the resolved plan seeded straight into the context.
"""

from __future__ import annotations

from tripfinder.ai.factory import build_llm_provider
from tripfinder.domain.models import Research, ResearchStatus
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.runner import PipelineRunner, ProgressListener
from tripfinder.pipeline.steps.aggregation import AggregationStep
from tripfinder.pipeline.steps.comment_analysis import CommentAnalysisStep
from tripfinder.pipeline.steps.discovery import AgenticDiscoveryStep
from tripfinder.pipeline.steps.entity_resolution import EntityResolutionStep
from tripfinder.pipeline.steps.health import SourceHealthAssessmentStep
from tripfinder.pipeline.steps.prefilter import CheapPrefilterStep
from tripfinder.pipeline.steps.preflight import SourcePreflightStep
from tripfinder.pipeline.steps.query_understanding import QueryUnderstandingStep
from tripfinder.pipeline.steps.retrieval import ContentRetrievalStep
from tripfinder.pipeline.steps.summarization import SummarizationStep
from tripfinder.pipeline.steps.triage import DocumentTriageStep
from tripfinder.pipeline.steps.user_deduplication import UserDeduplicationStep
from tripfinder.settings import Settings
from tripfinder.sources.arctic_shift.adapter import ArcticShiftAdapter

# Plan §4.6's definitive order, plus the two steps the table numbers don't
# cover: Preflight runs before step 1 (§8.1 — before any budget or token is
# spent), and Source Health Assessment runs between steps 6 and 7 (§8.1 — as
# soon as the corpus is in, before the expensive analysis steps run on it).
_POST_UNDERSTANDING_STEPS = (
    AgenticDiscoveryStep,
    DocumentTriageStep,
    ContentRetrievalStep,
    CheapPrefilterStep,
    SourceHealthAssessmentStep,
    CommentAnalysisStep,
    EntityResolutionStep,
    UserDeduplicationStep,
    AggregationStep,
    SummarizationStep,
)


def build_pipeline_runner(*, on_progress: ProgressListener | None = None) -> PipelineRunner:
    """The full plan §4.6 pipeline, Preflight through Summarization."""
    return PipelineRunner(
        [
            SourcePreflightStep(),
            QueryUnderstandingStep(),
            *(cls() for cls in _POST_UNDERSTANDING_STEPS),
        ],
        on_progress=on_progress,
    )


def build_resumed_pipeline_runner(*, on_progress: ProgressListener | None = None) -> PipelineRunner:
    """The pipeline for a research resuming after clarification (plan §6).

    Preflight and Query Understanding already ran in the pass that paused
    for clarification; ``build_pipeline_context_for`` seeds their output
    (the resolved plan) straight into the resumed context instead of asking
    the model a question it already answered.
    """
    return PipelineRunner([cls() for cls in _POST_UNDERSTANDING_STEPS], on_progress=on_progress)


def is_resuming(research: Research) -> bool:
    """Whether this research is picking back up after clarification (plan §6).

    Only ``/clarify`` produces this combination: ``discovering`` with a
    ``resume_plan`` set. A fresh job is always claimed at ``pending`` and
    runs straight through to a terminal or halting status within one
    ``run_once`` call, so it is never persisted mid-run at ``discovering``.
    """
    return research.status is ResearchStatus.DISCOVERING and research.resume_plan is not None


def build_pipeline_context_for(research: Research, *, settings: Settings) -> PipelineContext:
    """A context wired to the real adapters this process is configured for.

    The source adapter is always Arctic Shift (plan §1 — the MVP's only
    one); the LLM provider follows ``settings.llm_provider``, which defaults
    to fake so no process reaches OpenAI without ``LLM_PROVIDER`` set
    explicitly (plan §9).
    """
    source = ArcticShiftAdapter()
    llm = build_llm_provider(settings.llm_provider, openai_api_key=settings.openai_api_key)
    context = PipelineContext(research=research, source=source, llm=llm)
    if research.resume_plan is not None:
        context.data["plan"] = research.resume_plan
    return context
