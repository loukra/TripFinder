"""FastAPI entrypoint. Phase 0: proves the process boots; no business logic."""

from fastapi import FastAPI

app = FastAPI(title="TripFinder")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
