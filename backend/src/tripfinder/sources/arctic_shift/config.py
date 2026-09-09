"""Configuration for the Arctic Shift adapter (plan §8: "configurable politeness").

Every value here is config, not a constant buried in the client — matching the
pattern already established for ``ResearchConfig`` (plan §1.1).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArcticShiftConfig(BaseModel):
    """Connection, retry, and politeness settings for :class:`ArcticShiftAdapter`."""

    base_url: str = "https://arctic-shift.photon-reddit.com"
    user_agent: str = (
        "TripFinder/0.1 (opinion-based travel research engine; "
        "https://github.com/loukra/TripFinder)"
    )
    requests_per_second: float = Field(default=2.0, gt=0.0)
    max_retries: int = Field(default=3, ge=0)
    backoff_base_seconds: float = Field(default=1.0, gt=0.0)
    timeout_seconds: float = Field(default=15.0, gt=0.0)
    health_check_timeout_seconds: float = Field(default=5.0, gt=0.0)
    page_size: int = Field(default=100, gt=0, le=100)
    bot_denylist: list[str] = Field(default_factory=list)
