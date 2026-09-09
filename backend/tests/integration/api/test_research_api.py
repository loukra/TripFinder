"""Thin research API, end to end on the fake pipeline (plan §10 Phase 3.5).

Exercises the acceptance path: submit a query, poll status, read results —
the same round trip the walking-skeleton frontend drives. The worker isn't
running as a separate process in tests, so ``run_once`` stands in for it,
same as the job-repository/worker-loop integration tests do.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.jobs.worker_loop import run_once


async def test_full_research_flow_create_process_then_fetch_results(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    create_response = client.post("/api/research", json={"query": "underrated states"})
    assert create_response.status_code == 201
    created = create_response.json()
    research_id = created["id"]
    assert created["status"] == "pending"

    pending_response = client.get(f"/api/research/{research_id}")
    assert pending_response.status_code == 200
    assert pending_response.json()["status"] == "pending"

    processed = await run_once(session_factory)
    assert processed is True

    completed_response = client.get(f"/api/research/{research_id}")
    assert completed_response.status_code == 200
    assert completed_response.json()["status"] == "completed"

    results_response = client.get(f"/api/research/{research_id}/results")
    assert results_response.status_code == 200
    results_body = results_response.json()
    assert results_body["status"] == "completed"
    assert [r["entity_name"] for r in results_body["results"]] == ["Alaska", "Oregon"]
    assert [r["supporter_count"] for r in results_body["results"]] == [3, 2]


def test_create_research_rejects_blank_query(client: TestClient) -> None:
    response = client.post("/api/research", json={"query": ""})

    assert response.status_code == 422


def test_get_research_returns_404_for_unknown_id(client: TestClient) -> None:
    response = client.get(f"/api/research/{uuid4()}")

    assert response.status_code == 404


def test_get_research_results_returns_404_for_unknown_id(client: TestClient) -> None:
    response = client.get(f"/api/research/{uuid4()}/results")

    assert response.status_code == 404
