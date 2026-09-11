"""Configuration for the Serper web search provider (plan §2.11).

Every value is config rather than a constant in the provider, matching
``ArcticShiftConfig`` and ``OpenAIConfig``. The API key is *not* here — it is
a secret, so it is passed in from ``Settings`` as a ``SecretStr`` and never
serialised alongside the rest of this model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SerperConfig(BaseModel):
    """Connection and retry settings for :class:`SerperSearchProvider`."""

    base_url: str = "https://google.serper.dev"
    max_retries: int = Field(default=2, ge=0)
    backoff_base_seconds: float = Field(default=1.0, gt=0.0)
    timeout_seconds: float = Field(default=15.0, gt=0.0)
    country: str = "us"
    """Serper's ``gl`` parameter — which Google locale answers the query."""
    language: str = "en"
    """Serper's ``hl`` parameter."""
