"""Full fake run, query → ranked result (plan §10 Phase 2 acceptance)."""

import time

import pytest

from tripfinder.domain.models import ResearchStatus
from tripfinder.pipeline.fake_pipeline import (
    build_fake_pipeline_context,
    build_fake_pipeline_runner,
)
from tripfinder.search.fake import FakeSearchProvider


async def test_a_complete_fake_research_runs_query_to_ranked_result_in_under_a_second() -> None:
    context = build_fake_pipeline_context("Most underrated US states for nature")
    runner = build_fake_pipeline_runner()

    started = time.monotonic()
    result_context = await runner.run(context)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert result_context.research.status == ResearchStatus.COMPLETED
    assert [r.entity_name for r in result_context.research.results] == ["Alaska", "Oregon"]
    assert [r.supporter_count for r in result_context.research.results] == [3, 2]
    assert result_context.research.results[0].share == pytest.approx(3 / 5)
    assert result_context.research.results[1].share == pytest.approx(2 / 5)


async def test_progress_is_recorded_for_every_step_in_order() -> None:
    context = build_fake_pipeline_context("underrated states")
    runner = build_fake_pipeline_runner()

    result_context = await runner.run(context)

    assert [event.step_name for event in result_context.progress] == [
        "fake_understanding",
        "fake_discovery",
        "fake_retrieval",
        "fake_analysis",
        "fake_aggregation",
    ]
    assert [event.sequence for event in result_context.progress] == [1, 2, 3, 4, 5]
    assert result_context.progress[-1].status == ResearchStatus.COMPLETED


async def test_identical_query_run_twice_yields_identical_ranked_results() -> None:
    runner = build_fake_pipeline_runner()

    first = await runner.run(build_fake_pipeline_context("underrated states"))
    second = await runner.run(build_fake_pipeline_context("underrated states"))

    assert first.research.results == second.research.results


class TestDiscoveryRunsOnTheFakeSearchProvider:
    """Plan §10 Phase 14.5 acceptance: a full run reaches ranked results with
    ``SEARCH_PROVIDER=fake``, no key and no network anywhere."""

    async def test_the_documents_came_through_the_search_provider(self) -> None:
        context = build_fake_pipeline_context("underrated states")
        assert isinstance(context.search, FakeSearchProvider)

        result_context = await build_fake_pipeline_runner().run(context)

        assert context.search.queries == ["underrated states"]
        assert [d.id for d in result_context.data["documents"]] == ["post1", "post2"]

    async def test_a_fixture_address_naming_no_post_never_becomes_a_document(self) -> None:
        """The fixture list includes a subreddit landing page on purpose."""
        context = await build_fake_pipeline_runner().run(
            build_fake_pipeline_context("underrated states")
        )

        assert len(context.data["documents"]) == 2
