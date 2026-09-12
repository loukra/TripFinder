"""Reading the research table as history (plan §2.15, Phase 14.9).

``list_recent`` is the only read in this repository that does not build a
``Research``. These tests pin the two things that makes it responsible for:
the order the rows come back in, and the counts it derives in the database
rather than in Python.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import Research, ResearchStatus, Result
from tripfinder.persistence.repositories import ResearchRepository

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _result(entity_id: str, name: str) -> Result:
    return Result(
        entity_id=entity_id,
        entity_name=name,
        supporter_count=3,
        share=0.5,
        respondent_pool_size=6,
        discussion_count=2,
        weighted_score=3.0,
        confidence=0.9,
    )


async def _store(
    session_factory: async_sessionmaker[AsyncSession], *research: Research
) -> None:
    async with session_factory() as session:
        repository = ResearchRepository(session)
        for one in research:
            await repository.create(one)


async def test_list_recent_returns_newest_first(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    oldest = make_research("oldest question")
    oldest.created_at = NOW - timedelta(days=2)
    middle = make_research("middle question")
    middle.created_at = NOW - timedelta(days=1)
    newest = make_research("newest question")
    newest.created_at = NOW
    await _store(session_factory, middle, oldest, newest)

    async with session_factory() as session:
        listed = await ResearchRepository(session).list_recent(limit=10)

    assert [summary.original_query for summary in listed] == [
        "newest question",
        "middle question",
        "oldest question",
    ]


async def test_runs_sharing_a_timestamp_are_ordered_deterministically(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """Paging must not show one run twice and skip another."""
    same_second = [make_research(f"question {index}") for index in range(6)]
    for one in same_second:
        one.created_at = NOW
    await _store(session_factory, *same_second)

    async with session_factory() as session:
        repository = ResearchRepository(session)
        first_page = await repository.list_recent(limit=3, offset=0)
        second_page = await repository.list_recent(limit=3, offset=3)

    seen = [summary.id for summary in (*first_page, *second_page)]
    assert len(set(seen)) == 6
    assert set(seen) == {one.id for one in same_second}


async def test_a_page_is_a_window_on_the_whole_table(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    runs = []
    for index in range(5):
        one = make_research(f"question {index}")
        one.created_at = NOW - timedelta(minutes=index)
        runs.append(one)
    await _store(session_factory, *runs)

    async with session_factory() as session:
        repository = ResearchRepository(session)
        page = await repository.list_recent(limit=2, offset=1)
        total = await repository.count()

    assert [summary.original_query for summary in page] == ["question 1", "question 2"]
    assert total == 5


async def test_count_is_zero_on_an_empty_table(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repository = ResearchRepository(session)
        assert await repository.count() == 0
        assert await repository.list_recent(limit=10) == []


async def test_summaries_count_both_result_lists_without_loading_them(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = make_research()
    research.status = ResearchStatus.COMPLETED
    research.normalized_query = "underrated us nature destinations"
    research.results = [_result("state:alaska", "Alaska"), _result("state:oregon", "Oregon")]
    research.weak_results = [_result("state:idaho", "Idaho")]
    await _store(session_factory, research)

    async with session_factory() as session:
        [summary] = await ResearchRepository(session).list_recent(limit=10)

    assert summary.id == research.id
    assert summary.status is ResearchStatus.COMPLETED
    assert summary.normalized_query == "underrated us nature destinations"
    assert summary.result_count == 2
    assert summary.weak_result_count == 1
