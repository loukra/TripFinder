"""Looking an answer up by plan, against a real Postgres (plan §2.15, Phase 14.10).

The step decides whether a stored run *may* answer; this decides which row
comes back. Both matter, and only this half can be wrong in a way no unit
test would notice — an index that is not used, a JSONB null that is not
``NULL``, a tie broken the wrong way.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import (
    REUSABLE_STATUSES,
    EntityType,
    GeoScope,
    Research,
    ResearchPlan,
    ResearchStatus,
    Result,
    ReusedAnswer,
)
from tripfinder.domain.reuse import plan_fingerprint
from tripfinder.persistence.answer_archive import SqlAnswerArchive
from tripfinder.persistence.repositories import ResearchRepository

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


def _plan(**overrides: object) -> ResearchPlan:
    fields: dict[str, object] = {
        "normalized_query": "best national parks for avoiding crowds",
        "scope": GeoScope(type="country", value="United States"),
        "entity_granularity": EntityType.PARK,
        "granularity_confidence": 0.9,
        "topic": "national parks",
        "criteria": ["uncrowded"],
    }
    fields.update(overrides)
    return ResearchPlan.model_validate(fields)


def _research(
    *,
    status: ResearchStatus = ResearchStatus.COMPLETED,
    created_at: datetime = NOW - timedelta(days=10),
    plan: ResearchPlan | None = None,
    reused: ReusedAnswer | None = None,
    query: str = "quiet national parks",
) -> Research:
    plan = plan or _plan()
    return Research(
        original_query=query,
        normalized_query=plan.normalized_query,
        created_at=created_at,
        status=status,
        results=[
            Result(
                entity_id="park:great-basin",
                entity_name="Great Basin",
                supporter_count=41,
                share=0.36,
                respondent_pool_size=114,
                discussion_count=27,
                weighted_score=38.4,
                confidence=0.88,
            )
        ],
        plan=plan,
        plan_fingerprint=plan_fingerprint(plan),
        reused=reused,
    )


async def _persist(session_factory: async_sessionmaker[AsyncSession], *research: Research) -> None:
    async with session_factory() as session:
        repository = ResearchRepository(session)
        for one in research:
            await repository.create(one)


async def test_the_plan_and_its_key_survive_a_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Without this the run is unfindable, however good the fingerprint is."""
    stored = _research()
    await _persist(session_factory, stored)

    async with session_factory() as session:
        loaded = await ResearchRepository(session).get(stored.id)

    assert loaded is not None
    assert loaded.plan == stored.plan
    assert loaded.plan_fingerprint == plan_fingerprint(_plan())


async def test_a_reuse_marker_survives_a_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    original = uuid4()
    stored = _research(reused=ReusedAnswer(research_id=original, answered_at=NOW))
    await _persist(session_factory, stored)

    async with session_factory() as session:
        loaded = await ResearchRepository(session).get(stored.id)

    assert loaded is not None
    assert loaded.reused == ReusedAnswer(research_id=original, answered_at=NOW)


async def test_a_matching_run_is_found_by_its_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    stored = _research()
    await _persist(session_factory, stored)

    found = await SqlAnswerArchive(session_factory).find_by_fingerprint(
        fingerprint=plan_fingerprint(_plan()), not_before=NOW - timedelta(days=183)
    )

    assert found is not None
    assert found.id == stored.id
    assert [result.entity_name for result in found.results] == ["Great Basin"]


async def test_a_run_outside_the_window_is_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _persist(session_factory, _research(created_at=NOW - timedelta(days=200)))

    found = await SqlAnswerArchive(session_factory).find_by_fingerprint(
        fingerprint=plan_fingerprint(_plan()), not_before=NOW - timedelta(days=183)
    )

    assert found is None


async def test_a_budget_limited_run_is_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """§2.15.2: the query and ``REUSABLE_STATUSES`` are one list, not two."""
    await _persist(session_factory, _research(status=ResearchStatus.COMPLETED_PARTIAL))

    found = await SqlAnswerArchive(session_factory).find_by_fingerprint(
        fingerprint=plan_fingerprint(_plan()), not_before=NOW - timedelta(days=183)
    )

    assert found is not None
    assert found.status is ResearchStatus.COMPLETED_PARTIAL


async def test_a_degraded_run_is_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _persist(session_factory, _research(status=ResearchStatus.COMPLETED_DEGRADED))

    found = await SqlAnswerArchive(session_factory).find_by_fingerprint(
        fingerprint=plan_fingerprint(_plan()), not_before=NOW - timedelta(days=183)
    )

    assert found is None


async def test_a_cancelled_run_is_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _persist(session_factory, _research(status=ResearchStatus.CANCELLED))

    found = await SqlAnswerArchive(session_factory).find_by_fingerprint(
        fingerprint=plan_fingerprint(_plan()), not_before=NOW - timedelta(days=183)
    )

    assert found is None


async def test_every_reusable_status_is_findable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Whatever ``REUSABLE_STATUSES`` grows to, the query has to agree with it.

    The two used to be written out separately, which is how a row ends up
    findable but unusable — or, worse, the other way round.
    """
    # A key of its own per status, so each lookup can only return the row
    # it is about — no tie-breaking, no ordering, nothing to misread.
    for status in REUSABLE_STATUSES:
        plan = _plan(criteria=[status.value])
        await _persist(
            session_factory, _research(status=status, plan=plan, query=status.value)
        )

        found = await SqlAnswerArchive(session_factory).find_by_fingerprint(
            fingerprint=plan_fingerprint(plan), not_before=NOW - timedelta(days=183)
        )

        assert found is not None, status
        assert found.status is status


async def test_a_run_that_was_itself_reusing_is_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A JSONB column is only ``NULL`` if it is written as ``NULL``, not ``"null"``."""
    await _persist(
        session_factory,
        _research(reused=ReusedAnswer(research_id=uuid4(), answered_at=NOW - timedelta(days=40))),
    )

    found = await SqlAnswerArchive(session_factory).find_by_fingerprint(
        fingerprint=plan_fingerprint(_plan()), not_before=NOW - timedelta(days=183)
    )

    assert found is None


async def test_the_newest_matching_run_wins(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    older = _research(created_at=NOW - timedelta(days=100), query="older ask")
    newer = _research(created_at=NOW - timedelta(days=2), query="newer ask")
    await _persist(session_factory, older, newer)

    found = await SqlAnswerArchive(session_factory).find_by_fingerprint(
        fingerprint=plan_fingerprint(_plan()), not_before=NOW - timedelta(days=183)
    )

    assert found is not None
    assert found.id == newer.id


async def test_a_different_plan_finds_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _persist(session_factory, _research())

    found = await SqlAnswerArchive(session_factory).find_by_fingerprint(
        fingerprint=plan_fingerprint(_plan(criteria=["cheap"])),
        not_before=NOW - timedelta(days=183),
    )

    assert found is None


async def test_a_run_from_before_this_phase_is_simply_not_reusable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Every new column is nullable; old rows keep their answers and stop matching."""
    legacy = _research()
    legacy.plan = None
    legacy.plan_fingerprint = None
    await _persist(session_factory, legacy)

    found = await SqlAnswerArchive(session_factory).find_by_fingerprint(
        fingerprint=plan_fingerprint(_plan()), not_before=NOW - timedelta(days=183)
    )

    assert found is None
