"""The composition root (plan §10 Phase 13): which steps run, in what order, and
which adapters a process gets. No network, no LLM — constructing an
``ArcticShiftAdapter`` or a ``FakeLLMProvider`` does no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.domain.models import EntityType, GeoScope, Research, ResearchPlan, ResearchStatus
from tripfinder.pipeline.base import PartialResults
from tripfinder.pipeline.real_pipeline import (
    build_pipeline_context_for,
    build_pipeline_runner,
    build_resumed_pipeline_runner,
    is_resuming,
)
from tripfinder.settings import Settings
from tripfinder.sources.arctic_shift.adapter import ArcticShiftAdapter

_FULL_ORDER = [
    "source_preflight",
    "query_understanding",
    "agentic_discovery",
    "document_triage",
    "content_retrieval",
    "cheap_prefilter",
    "source_health_assessment",
    "comment_analysis",
    "entity_resolution",
    "user_deduplication",
    "aggregation",
    "summarization",
]


def _research(*, status: ResearchStatus = ResearchStatus.PENDING) -> Research:
    return Research(original_query="underrated states", created_at=datetime.now(UTC), status=status)


def _plan() -> ResearchPlan:
    return ResearchPlan(
        normalized_query="underrated states",
        scope=GeoScope(type="country", value="United States"),
        entity_granularity=EntityType.STATE,
        granularity_confidence=0.9,
        topic="nature",
    )


def test_the_full_pipeline_runs_every_step_in_plan_order() -> None:
    runner = build_pipeline_runner()

    assert [step.name for step in runner.steps] == _FULL_ORDER


def test_the_resumed_pipeline_skips_preflight_and_query_understanding() -> None:
    runner = build_resumed_pipeline_runner()

    assert [step.name for step in runner.steps] == _FULL_ORDER[2:]


def test_is_resuming_is_false_for_a_fresh_pending_research() -> None:
    assert is_resuming(_research()) is False


def test_is_resuming_is_false_for_discovering_without_a_resume_plan() -> None:
    """A confident, uninterrupted run also passes through ``discovering`` —
    only a persisted ``resume_plan`` means this is a clarified research."""
    assert is_resuming(_research(status=ResearchStatus.DISCOVERING)) is False


def test_is_resuming_is_true_only_once_clarify_has_set_a_resume_plan() -> None:
    research = _research(status=ResearchStatus.DISCOVERING)
    research.resume_plan = _plan()

    assert is_resuming(research) is True


def test_context_uses_the_real_source_adapter() -> None:
    context = build_pipeline_context_for(_research(), settings=Settings())

    assert isinstance(context.source, ArcticShiftAdapter)
    assert context.source.name == "arctic_shift"


def test_context_defaults_to_the_fake_llm_provider() -> None:
    """Plan §9: ``LLM_PROVIDER`` must be set explicitly before anything reaches OpenAI."""
    context = build_pipeline_context_for(_research(), settings=Settings())

    assert isinstance(context.llm, FakeLLMProvider)


def test_context_does_not_seed_a_plan_when_not_resuming() -> None:
    context = build_pipeline_context_for(_research(), settings=Settings())

    assert "plan" not in context.data


def test_context_seeds_the_resume_plan_for_a_clarified_research() -> None:
    research = _research(status=ResearchStatus.DISCOVERING)
    research.resume_plan = _plan()

    context = build_pipeline_context_for(research, settings=Settings())

    assert context.data["plan"] is research.resume_plan


def test_context_carries_the_partial_results_listener_it_was_given() -> None:
    """Plan §2.13: the analysis step reports snapshots through the context, so
    a composition root that dropped the listener would leave a run silent for
    its whole duration with nothing failing to say so."""

    async def listener(partial: PartialResults) -> None:  # pragma: no cover - never called
        raise AssertionError("not called by construction")

    context = build_pipeline_context_for(
        _research(), settings=Settings(), on_partial_results=listener
    )

    assert context.on_partial_results is listener


def test_a_context_built_without_one_simply_reports_nothing() -> None:
    context = build_pipeline_context_for(_research(), settings=Settings())

    assert context.on_partial_results is None
