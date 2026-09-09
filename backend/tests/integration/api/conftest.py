"""API test client wired to the real, throwaway Postgres (plan §9).

Enters the app's lifespan so ``configure_session_factory`` runs against the
testcontainers database rather than the local dev default.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tripfinder.main import app


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
