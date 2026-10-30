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
from tripfinder.domain.ports import AnswerArchive
from tripfinder.domain.usage import TokenLedger
from tripfinder.pipeline.base import PartialResultsListener, PipelineContext
from tripfinder.pipeline.runner import PipelineRunner, ProgressListener
from tripfinder.pipeline.steps.aggregation import AggregationStep
from tripfinder.pipeline.steps.answer_reuse import AnswerReuseStep
from tripfinder.pipeline.steps.entity_resolution import EntityResolutionStep
from tripfinder.pipeline.steps.health import SourceHealthAssessmentStep
from tripfinder.pipeline.steps.preflight import SourcePreflightStep
from tripfinder.pipeline.steps.query_understanding import QueryUnderstandingStep
from tripfinder.pipeline.steps.summarization import SummarizationStep
from tripfinder.pipeline.steps.user_deduplication import UserDeduplicationStep
from tripfinder.pipeline.streaming.orchestrator import StreamingStrandsStep
from tripfinder.search.factory import build_search_provider
from tripfinder.settings import Settings
from tripfinder.sources.arctic_shift.adapter import ArcticShiftAdapter

# Plan §4.6's order, with steps 3-7 collapsed into one concurrent phase
# (§2.14.2). Preflight still runs before step 1 (§8.1 — before any budget or
# token is spent).
#
# Source Health Assessment used to sit between steps 6 and 7, so that a
# broken source stopped the run before analysis was paid for. A pipeline
# cannot hold that position — analysis begins while retrieval is still
# happening — so the guarantee moved inside: `HealthGate` admits no analysis
# call until the source has returned `minPostsRetrieved` documents, and the
# step here keeps its second job, which is deciding what the run's outcome
# is (§8.1).
#
# `AnswerReuseStep` (§4.6 step 1.5) heads the list because it is the last
# chance to not spend anything: everything below it costs money, and it is
# the step that may find the question has already been answered (§2.15).
# Heading *this* tuple rather than sitting in `build_pipeline_runner` also
# puts it in the resumed pipeline, where it belongs — a run that paused for
# clarification has just settled on a plan, and a plan is exactly what the
# archive is keyed on.
_POST_UNDERSTANDING_STEPS = (
    AnswerReuseStep,
    StreamingStrandsStep,
    SourceHealthAssessmentStep,
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


def build_pipeline_context_for(
    research: Research,
    *,
    settings: Settings,
    on_partial_results: PartialResultsListener | None = None,
    archive: AnswerArchive | None = None,
) -> PipelineContext:
    """A context wired to the real adapters this process is configured for.

    The source adapter is always Arctic Shift (plan §1 — the MVP's only
    one). The LLM and search providers follow ``settings``, and both default
    to fake, so no process reaches OpenAI or Serper without ``LLM_PROVIDER``
    / ``SEARCH_PROVIDER`` set explicitly (plan §9, §2.11).

    ``on_partial_results`` is where provisional rankings go while the run is
    still analysing (plan §2.13). Left unset, the run produces none — the
    pipeline is unchanged, it simply reports once at the end as it did
    before.

    ``archive`` is the earlier answers this run may reuse (plan §2.15).
    Left unset, it reuses nothing and does all the work itself — which is
    what every caller without a database wants, and what every run did
    before 14.10.

    The token ledger is created here, given to the provider and kept on the
    context, so that the thing that spends and the thing that reports are
    the same object rather than two counts that can disagree.
    """
    source = ArcticShiftAdapter()
    ledger = TokenLedger()
    llm = build_llm_provider(
        settings.llm_provider, openai_api_key=settings.openai_api_key, ledger=ledger
    )
    search = build_search_provider(settings.search_provider, serper_api_key=settings.serper_api_key)
    context = PipelineContext(
        research=research,
        source=source,
        search=search,
        llm=llm,
        archive=archive,
        usage=ledger,
        on_partial_results=on_partial_results,
    )
    if research.resume_plan is not None:
        context.data["plan"] = research.resume_plan
    return context
