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
    max_results_per_query: int = Field(default=10, gt=0)
    """Serper's ceiling for a query carrying a ``site:`` operator.

    Measured, not documented by them: on a free account, ``site:reddit.com``
    with ``num=10`` succeeds, and the identical query with ``num=25`` is
    rejected with ``HTTP 400 "Query pattern not allowed for free accounts"``
    — a message that names the operator but is actually about the
    combination. Since every discovery query carries that operator (plan
    §2.11), an unclamped request would fail *every* search and take the whole
    research down as ``source_unavailable``.

    Ten is also Google's own first page, which is where the relevance is.
    Raise this if the account is upgraded; it is config for that reason.
    """
