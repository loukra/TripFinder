"""Request-scoped DB session dependency (plan §10 Phase 3.5).

The session factory is configured once at app startup (``main.py``'s
lifespan) and reconfigured by tests to point at a throwaway Postgres.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_session_factory: async_sessionmaker[AsyncSession] | None = None


def configure_session_factory(session_factory: async_sessionmaker[AsyncSession]) -> None:
    global _session_factory
    _session_factory = session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("session factory not configured — app startup did not run")
    async with _session_factory() as session:
        yield session
