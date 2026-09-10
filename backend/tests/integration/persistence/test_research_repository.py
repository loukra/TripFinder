"""Research repository integration tests (plan §10 Phase 3).

Real Postgres via testcontainers, no fake source/LLM involved — these tests
exercise persistence in isolation from the pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import (
    Research,
    ResearchDiagnostics,
    ResearchFlag,
    ResearchStatus,
    Result,
    SourceHealth,
    SourceOutcome,
    SuppressionReason,
    TriageDecidedBy,
    TriageDecision,
    TriageVerdict,
)
from tripfinder.persistence.repositories import ResearchNotFoundError, ResearchRepository


async def test_create_and_get_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = make_research()

    async with session_factory() as session:
        await ResearchRepository(session).create(research)

    async with session_factory() as session:
        fetched = await ResearchRepository(session).get(research.id)

    assert fetched is not None
    assert fetched.id == research.id
    assert fetched.original_query == research.original_query
    assert fetched.status == ResearchStatus.PENDING


async def test_get_returns_none_for_unknown_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        fetched = await ResearchRepository(session).get(uuid4())

    assert fetched is None


async def test_repeated_identical_search_creates_two_distinct_records(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """Plan §10 Phase 3 acceptance: two identical searches, two distinct records."""
    first = make_research()
    second = make_research()

    assert first.id != second.id

    async with session_factory() as session:
        repo = ResearchRepository(session)
        await repo.create(first)
        await repo.create(second)

    async with session_factory() as session:
        repo = ResearchRepository(session)
        fetched_first = await repo.get(first.id)
        fetched_second = await repo.get(second.id)

    assert fetched_first is not None
    assert fetched_second is not None
    assert fetched_first.id != fetched_second.id
    assert fetched_first.original_query == fetched_second.original_query == first.original_query


async def test_save_persists_updated_status_and_results(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)

    research.status = ResearchStatus.COMPLETED
    research.normalized_query = "underrated us nature destinations"
    research.statistics = {"documents_retrieved": 3}
    research.results = [
        Result(
            entity_id="alaska",
            entity_name="Alaska",
            supporter_count=3,
            share=1.0,
            respondent_pool_size=3,
            discussion_count=2,
            weighted_score=3.0,
            confidence=1.0,
        )
    ]

    async with session_factory() as session:
        await ResearchRepository(session).save(research)

    async with session_factory() as session:
        fetched = await ResearchRepository(session).get(research.id)

    assert fetched is not None
    assert fetched.status == ResearchStatus.COMPLETED
    assert fetched.normalized_query == "underrated us nature destinations"
    assert fetched.statistics == {"documents_retrieved": 3}
    assert [r.entity_name for r in fetched.results] == ["Alaska"]


async def test_save_on_never_created_research_raises(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    research = make_research()  # never persisted via create()

    async with session_factory() as session:
        with pytest.raises(ResearchNotFoundError):
            await ResearchRepository(session).save(research)


async def test_completed_research_can_be_retrieved_after_a_fresh_session(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """PROJECT.md §3 Phase 3: completed research can be retrieved (resume/read)."""
    research = make_research()
    research.status = ResearchStatus.COMPLETED
    research.results = [
        Result(
            entity_id="oregon",
            entity_name="Oregon",
            supporter_count=5,
            share=0.5,
            respondent_pool_size=10,
            discussion_count=4,
            weighted_score=5.0,
            confidence=0.9,
        )
    ]

    async with session_factory() as session:
        await ResearchRepository(session).create(research)

    async with session_factory() as session:
        fetched = await ResearchRepository(session).get(research.id)

    assert fetched is not None
    assert fetched.status == ResearchStatus.COMPLETED
    assert fetched.results[0].entity_name == "Oregon"


async def test_diagnostics_survive_a_round_trip(
    session_factory: async_sessionmaker[AsyncSession], make_research: Callable[..., Research]
) -> None:
    """Plan §0.1 rule 1 — counts and reasons are persisted in the snapshot."""
    research = make_research()
    research.diagnostics.source_health = [
        SourceHealth(
            adapter="arctic_shift",
            calls_attempted=10,
            calls_succeeded=5,
            calls_failed=5,
            failure_kinds={"timeout": 5},
            success_rate=0.5,
        )
    ]
    research.diagnostics.source_outcome = SourceOutcome.DEGRADED
    research.diagnostics.triage_decisions = [
        TriageDecision(
            document_id="d1",
            verdict=TriageVerdict.EXCLUDE,
            reason="only 2 comments",
            confidence=1.0,
            decided_by=TriageDecidedBy.RULE,
        )
    ]
    research.diagnostics.record_suppression(
        step="document_triage", reason=SuppressionReason.TRIAGE_EXCLUDED, count=3
    )
    research.diagnostics.raise_flag(ResearchFlag.LOW_POLLING_DOCUMENT_RATIO)

    async with session_factory() as session:
        await ResearchRepository(session).create(research)

    async with session_factory() as session:
        loaded = await ResearchRepository(session).get(research.id)

    assert loaded is not None
    assert loaded.diagnostics == research.diagnostics


async def test_saving_updates_diagnostics_on_an_existing_research(
    session_factory: async_sessionmaker[AsyncSession], make_research: Callable[..., Research]
) -> None:
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)

    research.diagnostics.record_suppression(
        step="cheap_prefilter", reason=SuppressionReason.PREFILTER_TOO_SHORT, count=7
    )
    async with session_factory() as session:
        await ResearchRepository(session).save(research)

    async with session_factory() as session:
        loaded = await ResearchRepository(session).get(research.id)

    assert loaded is not None
    assert loaded.diagnostics.suppressions[0].count == 7


async def test_weak_results_survive_a_round_trip(
    session_factory: async_sessionmaker[AsyncSession], make_research: Callable[..., Research]
) -> None:
    """plan §4.4: entities below the strong threshold are persisted, not dropped."""
    research = make_research()
    research.status = ResearchStatus.COMPLETED
    research.weak_results = [
        Result(
            entity_id="new_mexico",
            entity_name="New Mexico",
            supporter_count=2,
            share=0.2,
            respondent_pool_size=10,
            discussion_count=1,
            weighted_score=1.5,
            confidence=0.7,
        )
    ]

    async with session_factory() as session:
        await ResearchRepository(session).create(research)

    async with session_factory() as session:
        fetched = await ResearchRepository(session).get(research.id)

    assert fetched is not None
    assert [r.entity_name for r in fetched.weak_results] == ["New Mexico"]


async def test_saving_updates_weak_results_on_an_existing_research(
    session_factory: async_sessionmaker[AsyncSession], make_research: Callable[..., Research]
) -> None:
    research = make_research()
    async with session_factory() as session:
        await ResearchRepository(session).create(research)

    research.weak_results = [
        Result(
            entity_id="new_mexico",
            entity_name="New Mexico",
            supporter_count=2,
            share=0.2,
            respondent_pool_size=10,
            discussion_count=1,
            weighted_score=1.5,
            confidence=0.7,
        )
    ]
    async with session_factory() as session:
        await ResearchRepository(session).save(research)

    async with session_factory() as session:
        loaded = await ResearchRepository(session).get(research.id)

    assert loaded is not None
    assert [r.entity_name for r in loaded.weak_results] == ["New Mexico"]


async def test_a_research_with_no_diagnostics_loads_as_empty(
    session_factory: async_sessionmaker[AsyncSession], make_research: Callable[..., Research]
) -> None:
    research = make_research()

    async with session_factory() as session:
        await ResearchRepository(session).create(research)

    async with session_factory() as session:
        loaded = await ResearchRepository(session).get(research.id)

    assert loaded is not None
    assert loaded.diagnostics == ResearchDiagnostics()
