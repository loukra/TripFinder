"""Assembles the Phase 2 fake pipeline: real runner, fake source and LLM.

Demonstrates the acceptance criterion in plan §10 — a complete fake research
runs query → ranked result with zero external calls.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.domain.models import Research, ResearchStatus
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.runner import PipelineRunner
from tripfinder.pipeline.steps.fake import (
    FakeAggregationStep,
    FakeAnalysisResponse,
    FakeAnalysisStep,
    FakeDiscoveryStep,
    FakeMention,
    FakeRetrievalStep,
    FakeUnderstandingStep,
)
from tripfinder.sources.fake.adapter import FakeSourceAdapter
from tripfinder.sources.fake.fixtures import fixture_comments, fixture_documents

# Mirrors the authors in sources/fake/fixtures.py: u1, u2, u4 favor Alaska;
# u3, u5 favor Oregon.
_DEFAULT_MENTIONS = FakeAnalysisResponse(
    mentions=[
        FakeMention(entity_name="Alaska", user_id="u1"),
        FakeMention(entity_name="Alaska", user_id="u2"),
        FakeMention(entity_name="Oregon", user_id="u3"),
        FakeMention(entity_name="Alaska", user_id="u4"),
        FakeMention(entity_name="Oregon", user_id="u5"),
    ]
)


def build_fake_pipeline_context(query: str) -> PipelineContext:
    """A ready-to-run context wired to the default fixtures."""
    research = Research(
        original_query=query,
        created_at=datetime.now(UTC),
        status=ResearchStatus.PENDING,
    )
    source = FakeSourceAdapter(documents=fixture_documents(), comments=fixture_comments())
    llm = FakeLLMProvider({FakeAnalysisResponse: _DEFAULT_MENTIONS})
    return PipelineContext(research=research, source=source, llm=llm)


def build_fake_pipeline_runner() -> PipelineRunner:
    """The runner for the coarse-grained Phase 2 fake pipeline."""
    return PipelineRunner(
        [
            FakeUnderstandingStep(),
            FakeDiscoveryStep(),
            FakeRetrievalStep(),
            FakeAnalysisStep(),
            FakeAggregationStep(),
        ]
    )
