"""Plan §10 Phase 13: OpenAPI documents every endpoint, and a bug never leaks a traceback."""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tripfinder.main import app


def test_openapi_schema_documents_every_endpoint(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert set(schema["paths"]) == {
        "/api/research",
        "/api/research/{research_id}",
        "/api/research/{research_id}/clarify",
        "/api/research/{research_id}/cancel",
        "/api/research/{research_id}/results",
        "/api/research/{research_id}/evidence",
        "/health",
    }


def test_documented_error_responses_include_the_409_and_404_cases(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    results_responses = schema["paths"]["/api/research/{research_id}/results"]["get"]["responses"]
    assert "404" in results_responses
    assert "409" in results_responses


@pytest.fixture
def lenient_client(database_url: str) -> Iterator[TestClient]:
    """The regular ``client`` fixture's ``TestClient`` re-raises a handled exception after
    sending its response, so this test needs ``raise_server_exceptions=False`` to see the
    response the handler actually produced, the way a real client would."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_an_unexpected_error_returns_a_consistent_json_body_not_a_traceback(
    lenient_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(self: object, research_id: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("tripfinder.persistence.repositories.ResearchRepository.get", _boom)

    response = lenient_client.get(f"/api/research/{uuid4()}")

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
