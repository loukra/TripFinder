"""The history endpoint (plan §2.15, Phase 14.9).

``GET /api/research`` is a read of the table and nothing else: it starts no
run, reaches no source and calls no model. What it must get right is the
same thing every other endpoint in this router must get right — a run that
broke may not be listed in the words of a run that looked and found little
(plan §0.1).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.api.messages import STATUS_MESSAGES
from tripfinder.domain.models import (
    FailureKind,
    Research,
    ResearchFailure,
    ResearchStatus,
    Result,
)
from tripfinder.jobs.worker_loop import run_once
from tripfinder.persistence.repositories import ResearchRepository

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _result(name: str) -> Result:
    return Result(
        entity_id=f"state:{name.lower()}",
        entity_name=name,
        supporter_count=5,
        share=0.5,
        respondent_pool_size=10,
        discussion_count=3,
        weighted_score=5.0,
        confidence=0.9,
    )


async def _persist(
    session_factory: async_sessionmaker[AsyncSession], *research: Research
) -> None:
    async with session_factory() as session:
        repository = ResearchRepository(session)
        for one in research:
            await repository.create(one)


def test_an_empty_history_is_an_empty_list_not_an_error(client: TestClient) -> None:
    """The page has to be able to say "nothing yet" rather than "failed to load"."""
    response = client.get("/api/research")

    assert response.status_code == 200
    assert response.json() == {"total": 0, "limit": 20, "offset": 0, "runs": []}


async def test_runs_are_listed_newest_first_with_question_date_and_outcome(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    older = make_research("underrated states for nature")
    older.created_at = NOW - timedelta(days=3)
    older.status = ResearchStatus.COMPLETED
    older.results = [_result("Alaska"), _result("Oregon")]
    newer = make_research("underrated countries for nature")
    newer.created_at = NOW
    newer.status = ResearchStatus.COMPLETED_PARTIAL
    newer.results = [_result("Georgia")]
    await _persist(session_factory, older, newer)

    body = client.get("/api/research").json()

    assert body["total"] == 2
    assert [run["query"] for run in body["runs"]] == [
        "underrated countries for nature",
        "underrated states for nature",
    ]
    assert [run["status"] for run in body["runs"]] == ["completed_partial", "completed"]
    assert [run["result_count"] for run in body["runs"]] == [1, 2]
    assert body["runs"][0]["created_at"].startswith("2026-03-01T12:00:00")


async def test_a_partial_run_is_not_described_as_a_finished_one(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """Plan §0.1 rule 4, one status ahead of the click rather than after it."""
    finished = make_research("finished")
    finished.created_at = NOW
    finished.status = ResearchStatus.COMPLETED
    cut_short = make_research("cut short")
    cut_short.created_at = NOW - timedelta(minutes=1)
    cut_short.status = ResearchStatus.COMPLETED_PARTIAL
    await _persist(session_factory, finished, cut_short)

    runs = client.get("/api/research").json()["runs"]

    messages = {run["query"]: run["message"] for run in runs}
    assert messages["finished"] == STATUS_MESSAGES[ResearchStatus.COMPLETED]
    assert messages["cut short"] == STATUS_MESSAGES[ResearchStatus.COMPLETED_PARTIAL]
    assert messages["finished"] != messages["cut short"]


async def test_a_failed_run_holding_a_ranking_lists_no_result_count(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """A run can break after aggregation, so its row holds results its page refuses
    to serve (plan §7.1). Listing "2 results" there would let a broken run borrow
    the sentence a thin-but-honest one owns (plan §0.1)."""
    broken = make_research("broke after ranking")
    broken.created_at = NOW
    broken.status = ResearchStatus.FAILED
    broken.results = [_result("Alaska"), _result("Oregon")]
    broken.diagnostics.failure = ResearchFailure(
        kind=FailureKind.UNEXPECTED_ERROR, step="summarization", detail="boom"
    )
    await _persist(session_factory, broken)

    [run] = client.get("/api/research").json()["runs"]

    assert run["status"] == "failed"
    assert run["result_count"] is None
    assert client.get(f"/api/research/{run['id']}/results").status_code == 409


async def test_a_cancelled_run_lists_the_snapshot_it_still_serves(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """§2.13.3: a cancelled run with a snapshot has a results page, so it has a count."""
    interrupted = make_research("stopped mid-analysis")
    interrupted.created_at = NOW
    interrupted.status = ResearchStatus.CANCELLED
    interrupted.results = [_result("Alaska")]
    empty = make_research("stopped before anything was ranked")
    empty.created_at = NOW - timedelta(minutes=1)
    empty.status = ResearchStatus.CANCELLED
    await _persist(session_factory, interrupted, empty)

    listed = client.get("/api/research").json()["runs"]
    counts = {run["query"]: run["result_count"] for run in listed}

    assert counts["stopped mid-analysis"] == 1
    assert counts["stopped before anything was ranked"] is None


async def test_a_run_still_in_flight_appears_in_the_history(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    running = make_research("still going")
    running.created_at = NOW
    running.status = ResearchStatus.RETRIEVING
    await _persist(session_factory, running)

    [run] = client.get("/api/research").json()["runs"]

    assert run["status"] == "retrieving"
    assert run["result_count"] is None
    assert run["message"] == STATUS_MESSAGES[ResearchStatus.RETRIEVING]


async def test_history_pages_through_the_table(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    runs = []
    for index in range(5):
        one = make_research(f"question {index}")
        one.created_at = NOW - timedelta(minutes=index)
        runs.append(one)
    await _persist(session_factory, *runs)

    body = client.get("/api/research", params={"limit": 2, "offset": 2}).json()

    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 2
    assert [run["query"] for run in body["runs"]] == ["question 2", "question 3"]


def test_history_rejects_a_page_size_it_will_not_serve(client: TestClient) -> None:
    assert client.get("/api/research", params={"limit": 0}).status_code == 422
    assert client.get("/api/research", params={"limit": 101}).status_code == 422
    assert client.get("/api/research", params={"offset": -1}).status_code == 422


async def test_a_finished_run_is_reopened_from_history_without_running_anything_again(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Phase 14.9 acceptance: the same ranking, statistics and diagnostics, and no
    new work — the queue is empty when the second read is over."""
    created = client.post("/api/research", json={"query": "underrated states"}).json()
    assert await run_once(session_factory) is True
    first_read = client.get(f"/api/research/{created['id']}/results").json()
    first_status = client.get(f"/api/research/{created['id']}").json()

    [listed] = client.get("/api/research").json()["runs"]
    assert listed["id"] == created["id"]

    reopened = client.get(f"/api/research/{listed['id']}/results").json()
    reopened_status = client.get(f"/api/research/{listed['id']}").json()

    assert reopened == first_read
    assert reopened_status["statistics"] == first_status["statistics"]
    assert reopened_status["diagnostics"] == first_status["diagnostics"]
    assert await run_once(session_factory) is False


async def test_a_run_reopened_cold_carries_its_own_question(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> None:
    """A page opened from history has no memory of what was asked, so the run
    has to say (plan §2.15)."""
    research = make_research("underrated states for nature")
    research.created_at = NOW
    research.normalized_query = "underrated us states for nature"
    research.status = ResearchStatus.COMPLETED
    await _persist(session_factory, research)

    body = client.get(f"/api/research/{research.id}").json()

    assert body["query"] == "underrated states for nature"
    assert body["normalized_query"] == "underrated us states for nature"
    assert body["created_at"].startswith("2026-03-01T12:00:00")
