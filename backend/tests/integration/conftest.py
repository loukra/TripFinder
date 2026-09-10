"""Shared fixtures for integration tests — a real, throwaway Postgres (plan §9).

A session-scoped container avoids paying container startup cost per test;
tables are truncated after each test so tests stay independent.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from tripfinder.domain.models import Research, ResearchStatus
from tripfinder.persistence.database import make_engine, make_session_factory
from tripfinder.persistence.orm import Base
from tripfinder.pipeline.fake_pipeline import (
    build_fake_pipeline_context_for,
    build_fake_pipeline_runner,
)

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16") as container:
        url = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")

        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            command.upgrade(Config(str(ALEMBIC_INI)), "head")
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous

        yield url


@pytest.fixture
async def session_factory(
    database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine(database_url)
    try:
        yield make_session_factory(engine)
    finally:
        async with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                await connection.execute(table.delete())
        await engine.dispose()


@pytest.fixture(autouse=True)
def fake_pipeline_composition_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan §9: integration tests get a faked source and LLM, never the real ones.

    The worker's composition root (plan §10 Phase 13) defaults to the real
    pipeline — Arctic Shift and whatever ``LLM_PROVIDER`` says. Every
    integration test gets the fake pipeline instead, the same way it always
    has, without needing to know that switch happened.
    """
    monkeypatch.setattr(
        "tripfinder.jobs.worker_loop.build_pipeline_context_for",
        lambda research, **_kwargs: build_fake_pipeline_context_for(research),
    )
    monkeypatch.setattr(
        "tripfinder.jobs.worker_loop.build_pipeline_runner", build_fake_pipeline_runner
    )
    monkeypatch.setattr(
        "tripfinder.jobs.worker_loop.build_resumed_pipeline_runner", build_fake_pipeline_runner
    )


@pytest.fixture
def make_research() -> Callable[..., Research]:
    """Factory for a fresh, unpersisted ``Research`` (shared across integration tests)."""

    def _make(query: str = "underrated US nature destinations") -> Research:
        return Research(
            original_query=query, created_at=datetime.now(UTC), status=ResearchStatus.PENDING
        )

    return _make
