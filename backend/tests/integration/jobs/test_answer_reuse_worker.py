"""A question answered twice, through the worker (plan §2.15, Phase 14.10).

The unit tests prove the rules; this proves the wiring. The worker is the
only process that can hand the pipeline an ``AnswerArchive``, and a step
that is never given one reuses nothing however correct it is.

The second run's pipeline ends in a step that raises if it is ever reached,
which is what makes "without a discovery, retrieval or analysis call" an
assertion rather than a description.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.config import ResearchConfig, ReuseConfig
from tripfinder.domain.models import (
    EntityType,
    GeoScope,
    Research,
    ResearchPlan,
    ResearchStatus,
    Result,
)
from tripfinder.jobs.repository import JobRepository
from tripfinder.jobs.worker_loop import run_once
from tripfinder.persistence.repositories import ResearchRepository
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.runner import PipelineRunner, ProgressListener
from tripfinder.pipeline.steps.answer_reuse import AnswerReuseStep
from tripfinder.search.fake import FakeSearchProvider
from tripfinder.sources.fake.adapter import FakeSourceAdapter

PLAN = ResearchPlan(
    normalized_query="best national parks for avoiding crowds",
    scope=GeoScope(type="country", value="United States"),
    entity_granularity=EntityType.PARK,
    granularity_confidence=0.9,
    topic="national parks",
    criteria=["uncrowded"],
)

ANSWER = Result(
    entity_id="park:great-basin",
    entity_name="Great Basin",
    supporter_count=41,
    share=0.36,
    respondent_pool_size=114,
    discussion_count=27,
    weighted_score=38.4,
    confidence=0.88,
)


class _UnderstandsTheQuestion:
    """Stands in for Query Understanding: one cheap call, and a plan."""

    name = "query_understanding"

    async def run(self, context: PipelineContext) -> PipelineContext:
        context.data["plan"] = PLAN
        context.usage.record(None)
        context.research.normalized_query = PLAN.normalized_query
        context.research.status = ResearchStatus.DISCOVERING
        return context


class _DoesTheExpensiveWork:
    """Everything reuse is meant to avoid, compressed into one step."""

    name = "parallel_strands"

    async def run(self, context: PipelineContext) -> PipelineContext:
        for _ in range(130):
            context.usage.record(None)
        context.research.results = [ANSWER]
        context.research.statistics = {"posts_analyzed": 27}
        context.research.status = ResearchStatus.COMPLETED
        return context


class _MustNotRun:
    name = "parallel_strands"

    async def run(self, context: PipelineContext) -> PipelineContext:
        raise AssertionError("a reused answer must cost no discovery, retrieval or analysis")


@pytest.fixture
def compose(monkeypatch: pytest.MonkeyPatch) -> Callable[[bool], None]:
    """Point the worker at a pipeline whose last step is ours to choose."""

    def _compose(does_the_work: bool) -> None:
        def _context(
            research: Research,
            *,
            archive: object | None = None,
            **_kwargs: object,
        ) -> PipelineContext:
            return PipelineContext(
                research=research,
                source=FakeSourceAdapter(),
                search=FakeSearchProvider(),
                llm=object(),  # type: ignore[arg-type]
                archive=archive,  # type: ignore[arg-type]
            )

        def _runner(*, on_progress: ProgressListener | None = None) -> PipelineRunner:
            last = _DoesTheExpensiveWork() if does_the_work else _MustNotRun()
            return PipelineRunner(
                [_UnderstandsTheQuestion(), AnswerReuseStep(), last], on_progress=on_progress
            )

        monkeypatch.setattr("tripfinder.jobs.worker_loop.build_pipeline_context_for", _context)
        monkeypatch.setattr("tripfinder.jobs.worker_loop.build_pipeline_runner", _runner)

    return _compose


async def _ask(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    created_at: datetime,
    query: str,
    config: ResearchConfig | None = None,
) -> Research:
    research = Research(
        original_query=query,
        created_at=created_at,
        status=ResearchStatus.PENDING,
        research_config=config or ResearchConfig(),
    )
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    async with session_factory() as session:
        await JobRepository(session).enqueue(research.id)
    await run_once(session_factory)
    async with session_factory() as session:
        answered = await ResearchRepository(session).get(research.id)
    assert answered is not None
    return answered


async def test_the_second_asking_is_answered_from_the_first(
    session_factory: async_sessionmaker[AsyncSession],
    compose: Callable[[bool], None],
) -> None:
    compose(True)
    first = await _ask(session_factory, created_at=datetime.now(UTC), query="quiet national parks")
    assert first.status is ResearchStatus.COMPLETED
    assert first.statistics["llm_calls"] == 131

    compose(False)
    second = await _ask(
        session_factory,
        created_at=datetime.now(UTC),
        query="which national parks have the fewest crowds",
    )

    assert second.status is ResearchStatus.COMPLETED
    assert second.id != first.id
    assert [result.entity_name for result in second.results] == ["Great Basin"]
    assert second.reused is not None
    assert second.reused.research_id == first.id
    assert second.reused.answered_at == first.created_at


async def test_the_saving_is_a_number_on_the_two_runs(
    session_factory: async_sessionmaker[AsyncSession],
    compose: Callable[[bool], None],
) -> None:
    """Plan §2.15: what a hit saves is read off the runs, never asserted about them."""
    compose(True)
    first = await _ask(session_factory, created_at=datetime.now(UTC), query="quiet parks")

    compose(False)
    second = await _ask(session_factory, created_at=datetime.now(UTC), query="uncrowded parks")

    assert first.statistics["llm_calls"] == 131
    assert second.statistics["llm_calls"] == 1
    # The corpus figures describe the answer, which is the older run's.
    assert second.statistics["posts_analyzed"] == first.statistics["posts_analyzed"]


async def test_the_first_run_is_left_exactly_as_it_was(
    session_factory: async_sessionmaker[AsyncSession],
    compose: Callable[[bool], None],
) -> None:
    compose(True)
    first = await _ask(session_factory, created_at=datetime.now(UTC), query="quiet parks")

    compose(False)
    await _ask(session_factory, created_at=datetime.now(UTC), query="uncrowded parks")

    async with session_factory() as session:
        reread = await ResearchRepository(session).get(first.id)
    assert reread is not None
    assert reread.reused is None
    assert reread.statistics["llm_calls"] == 131


async def test_a_fresh_run_does_the_work_again_and_leaves_the_old_one_alone(
    session_factory: async_sessionmaker[AsyncSession],
    compose: Callable[[bool], None],
) -> None:
    """Plan §2.15 rule 2, end to end: a new id, a new run, nothing overwritten."""
    compose(True)
    first = await _ask(session_factory, created_at=datetime.now(UTC), query="quiet parks")

    config = ResearchConfig(reuse=ReuseConfig(enabled=False))
    fresh = await _ask(
        session_factory,
        created_at=datetime.now(UTC),
        query="quiet parks",
        config=config,
    )

    assert fresh.id != first.id
    assert fresh.reused is None
    assert fresh.statistics["llm_calls"] == 131
    async with session_factory() as session:
        reread = await ResearchRepository(session).get(first.id)
    assert reread is not None
    assert reread.status is ResearchStatus.COMPLETED


async def test_an_answer_past_the_window_is_paid_for_again(
    session_factory: async_sessionmaker[AsyncSession],
    compose: Callable[[bool], None],
) -> None:
    compose(True)
    await _ask(
        session_factory,
        created_at=datetime.now(UTC) - timedelta(days=400),
        query="quiet parks",
    )

    second = await _ask(session_factory, created_at=datetime.now(UTC), query="uncrowded parks")

    assert second.reused is None
    assert second.statistics["llm_calls"] == 131
