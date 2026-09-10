"""Worker process entrypoint (plan §10 Phase 3). Polls the job table forever."""

from __future__ import annotations

import asyncio

from tripfinder.jobs.worker_loop import run_worker_loop
from tripfinder.persistence.database import make_engine, make_session_factory
from tripfinder.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    asyncio.run(run_worker_loop(session_factory, settings=settings))


if __name__ == "__main__":
    main()
