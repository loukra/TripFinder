from datetime import UTC, datetime

import pytest

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.domain.models import Research, ResearchStatus
from tripfinder.pipeline.base import PipelineContext
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


def _context(llm: FakeLLMProvider | None = None) -> PipelineContext:
    research = Research(
        original_query="  Most Underrated States  ",
        created_at=datetime.now(UTC),
        status=ResearchStatus.PENDING,
    )
    source = FakeSourceAdapter(documents=fixture_documents(), comments=fixture_comments())
    return PipelineContext(research=research, source=source, llm=llm or FakeLLMProvider())


async def test_understanding_step_normalizes_query_and_advances_status() -> None:
    context = await FakeUnderstandingStep().run(_context())

    assert context.research.normalized_query == "most underrated states"
    assert context.research.status == ResearchStatus.DISCOVERING


async def test_discovery_step_populates_documents_from_source() -> None:
    context = await FakeDiscoveryStep().run(_context())

    assert [document.id for document in context.data["documents"]] == ["post1", "post2"]
    assert context.research.status == ResearchStatus.RETRIEVING


async def test_retrieval_step_fetches_comments_for_each_discovered_document() -> None:
    context = _context()
    context = await FakeDiscoveryStep().run(context)

    context = await FakeRetrievalStep().run(context)

    assert [comment.id for comment in context.data["comments"]] == ["c1", "c2", "c3", "c4", "c5"]
    assert context.research.status == ResearchStatus.ANALYZING


async def test_analysis_step_uses_llm_provider_and_advances_status() -> None:
    canned = FakeAnalysisResponse(mentions=[FakeMention(entity_name="Alaska", user_id="u1")])
    context = _context(llm=FakeLLMProvider({FakeAnalysisResponse: canned}))
    context.data["comments"] = []

    context = await FakeAnalysisStep().run(context)

    assert context.data["mentions"] == canned.mentions
    assert context.research.status == ResearchStatus.AGGREGATING


async def test_analysis_step_propagates_missing_fixture_as_failure() -> None:
    context = _context(llm=FakeLLMProvider())  # nothing registered
    context.data["comments"] = []

    with pytest.raises(LookupError):
        await FakeAnalysisStep().run(context)


async def test_aggregation_step_counts_distinct_supporters_and_ranks_by_count() -> None:
    context = _context()
    context.data["documents"] = fixture_documents()
    context.data["comments"] = [c for cs in fixture_comments().values() for c in cs]
    context.data["mentions"] = [
        FakeMention(entity_name="Alaska", user_id="u1"),
        FakeMention(entity_name="Alaska", user_id="u2"),
        FakeMention(entity_name="Oregon", user_id="u3"),
        FakeMention(entity_name="Alaska", user_id="u4"),
        FakeMention(entity_name="Oregon", user_id="u5"),
    ]

    context = await FakeAggregationStep().run(context)

    assert [r.entity_name for r in context.research.results] == ["Alaska", "Oregon"]
    assert [r.supporter_count for r in context.research.results] == [3, 2]
    assert context.research.results[0].respondent_pool_size == 5
    assert context.research.results[0].share == pytest.approx(3 / 5)
    assert context.research.status == ResearchStatus.COMPLETED


async def test_aggregation_step_ignores_duplicate_mentions_from_same_user() -> None:
    context = _context()
    context.data["documents"] = []
    context.data["comments"] = []
    context.data["mentions"] = [
        FakeMention(entity_name="Alaska", user_id="u1"),
        FakeMention(entity_name="Alaska", user_id="u1"),
    ]

    context = await FakeAggregationStep().run(context)

    assert context.research.results[0].supporter_count == 1


async def test_aggregation_step_with_no_mentions_produces_no_results() -> None:
    context = _context()
    context.data["documents"] = []
    context.data["comments"] = []
    context.data["mentions"] = []

    context = await FakeAggregationStep().run(context)

    assert context.research.results == []
    assert context.research.status == ResearchStatus.COMPLETED
