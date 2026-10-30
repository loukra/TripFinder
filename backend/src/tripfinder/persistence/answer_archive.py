"""Earlier answers, looked up by plan (plan §2.15, Phase 14.10).

The :class:`~tripfinder.domain.ports.AnswerArchive` side of reuse: given a
fingerprint and a cut-off date, the most recent stored run that carries it.

Two things this deliberately does **not** do.

It does not decide whether the run it found may be used. Status, the
reuse-of-a-reuse rule and the run's own consent all live in
``AnswerReuseStep``, where they can be read and tested without a database.
A repository that quietly filtered on status would put a rule nobody can
see between the question and the answer.

It does not hold a session. A pipeline step can run for minutes between one
query and the next, and a session kept open across that is a connection held
for nothing — so this takes the factory and opens a session per lookup, the
same way the worker's own callbacks do.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import Research
from tripfinder.persistence.repositories import ResearchRepository


class SqlAnswerArchive:
    """Every run this installation has ever completed, keyed by plan."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_by_fingerprint(
        self, *, fingerprint: str, not_before: datetime
    ) -> Research | None:
        async with self._session_factory() as session:
            return await ResearchRepository(session).find_by_fingerprint(
                fingerprint=fingerprint, not_before=not_before
            )
