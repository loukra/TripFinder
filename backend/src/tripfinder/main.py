"""FastAPI entrypoint (plan §10 Phase 3.5 — thin API; hardened in Phase 13).

Environment configuration is read through ``Settings`` (plan §2.9) rather
than by each module that happens to need a value.

**Read at startup, not at import.** The process environment is the source of
truth when the app actually runs, and tests point ``DATABASE_URL`` at a
throwaway Postgres *after* importing this module. Freezing settings at
import time silently sends those tests to the developer's own database.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tripfinder.api.dependencies import configure_session_factory
from tripfinder.api.research import router as research_router
from tripfinder.persistence.database import make_engine, make_session_factory
from tripfinder.settings import Settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    engine = make_engine(settings.database_url)
    configure_session_factory(make_session_factory(engine))
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="TripFinder", lifespan=lifespan)

# CORS is the one setting the app object needs before it starts, because
# middleware cannot be added to a running app.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[Settings.from_env().frontend_url],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(research_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """The error contract's last line (plan §10 Phase 13): never leak a stack trace.

    Every endpoint's *expected* failures already raise ``HTTPException`` with
    a typed body (plan §11). This is only for a bug — and a bug should still
    come back as the same JSON shape every other error does, not an ASGI
    server's default plaintext traceback.
    """
    logger.exception("unhandled error handling %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
