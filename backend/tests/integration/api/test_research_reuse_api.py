"""Reuse at the API boundary (plan §2.15, Phase 14.10).

Two obligations, and they are the whole phase as a user meets it.

**A reused answer says when it was produced, everywhere it is shown.** Three
endpoints describe one run's answer — the status poll, the results page and
the history row — and an answer labelled in one of them is labelled nowhere
that matters, because a client may only ever read one.

**A fresh run is one click away and never consults the cache.** Here that is
``fresh=true``, and what it must produce is an ordinary run with a new id,
with the decision written into the config the run keeps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.api.schemas import ResearchListItem, ResearchResultsResponse, ResearchStatusResponse
from tripfinder.domain.models import (
    Research,
    ResearchStatus,
    Result,
    ReusedAnswer,
)
from tripfinder.persistence.repositories import ResearchRepository

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
PRODUCED = datetime(2026, 3, 4, 9, 30, tzinfo=UTC)


def _result() -> Result:
    return Result(
        entity_id="park:great-basin",
        entity_name="Great Basin",
        supporter_count=41,
        share=0.36,
        respondent_pool_size=114,
        discussion_count=27,
        weighted_score=38.4,
        confidence=0.88,
    )


async def _persist_reused_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> Research:
    research = Research(
        original_query="which national parks have the fewest crowds",
        normalized_query="best national parks for avoiding crowds",
        created_at=NOW,
        status=ResearchStatus.COMPLETED,
        results=[_result()],
        statistics={"posts_analyzed": 27, "llm_calls": 1},
        reused=ReusedAnswer(research_id=uuid4(), answered_at=PRODUCED),
    )
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    return research


async def test_the_status_response_says_when_the_answer_was_produced(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    research = await _persist_reused_run(session_factory)

    body = client.get(f"/api/research/{research.id}").json()

    assert body["reused"]["answered_at"] == PRODUCED.isoformat().replace("+00:00", "Z")
    assert body["created_at"] != body["reused"]["answered_at"]


async def test_the_results_response_says_when_the_answer_was_produced(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    research = await _persist_reused_run(session_factory)

    body = client.get(f"/api/research/{research.id}/results").json()

    assert body["reused"]["answered_at"] == PRODUCED.isoformat().replace("+00:00", "Z")
    assert body["results"][0]["entity_name"] == "Great Basin"


async def test_the_history_row_says_when_the_answer_was_produced(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A row reading "Finished · today" over a March ranking is the §2.15 rule 1 failure."""
    research = await _persist_reused_run(session_factory)

    listed = client.get("/api/research").json()["runs"]

    assert [run["id"] for run in listed] == [str(research.id)]
    assert listed[0]["reused"]["answered_at"] == PRODUCED.isoformat().replace("+00:00", "Z")


async def test_a_run_that_did_its_own_work_carries_no_label(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The label means something only if most runs do not have it."""
    research = Research(
        original_query="quiet national parks",
        created_at=NOW,
        status=ResearchStatus.COMPLETED,
        results=[_result()],
    )
    async with session_factory() as session:
        await ResearchRepository(session).create(research)

    assert client.get(f"/api/research/{research.id}").json()["reused"] is None
    assert client.get(f"/api/research/{research.id}/results").json()["reused"] is None
    assert client.get("/api/research").json()["runs"][0]["reused"] is None


@pytest.mark.parametrize(
    "schema", [ResearchStatusResponse, ResearchResultsResponse, ResearchListItem]
)
def test_the_date_cannot_be_left_off_a_reused_answer(schema: type[BaseModel]) -> None:
    """Plan §2.15 rule 1, made impossible to get wrong rather than merely tested.

    The fact and the date are one object, so there is no shape of response
    that says "this answer was reused" without also saying when it was
    produced — a client cannot read the first and miss the second.
    """
    with pytest.raises(ValidationError):
        schema.model_validate(
            {
                "id": uuid4(),
                "status": ResearchStatus.COMPLETED,
                "message": "Finished.",
                "query": "quiet parks",
                "created_at": NOW,
                "statistics": {},
                "diagnostics": {},
                "percentages_suppressed": False,
                "results": [],
                "normalized_query": None,
                "result_count": 1,
                "reused": {"research_id": str(uuid4())},
            }
        )


def test_a_fresh_run_is_created_with_reuse_switched_off(client: TestClient) -> None:
    created = client.post("/api/research", json={"query": "quiet parks", "fresh": True})

    assert created.status_code == 201


async def test_the_decision_not_to_reuse_is_stored_on_the_run(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The worker reads it minutes later; a flag that lived in the request would be gone."""
    created = client.post("/api/research", json={"query": "quiet parks", "fresh": True}).json()

    async with session_factory() as session:
        research = await ResearchRepository(session).get(created["id"])

    assert research is not None
    assert research.research_config.reuse.enabled is False


async def test_an_ordinary_run_is_allowed_to_reuse(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    created = client.post("/api/research", json={"query": "quiet parks"}).json()

    async with session_factory() as session:
        research = await ResearchRepository(session).get(created["id"])

    assert research is not None
    assert research.research_config.reuse.enabled is True


async def test_a_fresh_run_gets_its_own_id(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Plan §2.15 rule 2: the old run stays in history, reachable and untouched."""
    existing = await _persist_reused_run(session_factory)

    created = client.post("/api/research", json={"query": "quiet parks", "fresh": True}).json()

    assert created["id"] != str(existing.id)
    assert client.get(f"/api/research/{existing.id}").status_code == 200


async def test_a_window_older_than_the_run_still_lists_it(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Reuse never removes anything: history is the whole table, labelled."""
    await _persist_reused_run(session_factory)
    older = Research(
        original_query="quiet national parks",
        created_at=NOW - timedelta(days=400),
        status=ResearchStatus.COMPLETED,
        results=[_result()],
    )
    async with session_factory() as session:
        await ResearchRepository(session).create(older)

    assert client.get("/api/research").json()["total"] == 2
