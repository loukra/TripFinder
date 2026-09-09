"""Worker process entrypoint (plan §10 Phase 3). Polls the job table forever."""

from __future__ import annotations

import asyncio
import os

from tripfinder.jobs.worker_loop import run_worker_loop
from tripfinder.persistence.database import DEFAULT_DATABASE_URL, make_engine, make_session_factory


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    asyncio.run(run_worker_loop(session_factory))


if __name__ == "__main__":
    main()
