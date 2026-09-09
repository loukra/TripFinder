"""FastAPI entrypoint (plan §10 Phase 3.5 — thin API on the fake pipeline)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tripfinder.api.dependencies import configure_session_factory
from tripfinder.api.research import router as research_router
from tripfinder.persistence.database import DEFAULT_DATABASE_URL, make_engine, make_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    engine = make_engine(database_url)
    configure_session_factory(make_session_factory(engine))
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="TripFinder", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(research_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
