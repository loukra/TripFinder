"""Configuration for the OpenAI provider (plan §10 Phase 7.5).

Follows ``ArcticShiftConfig``: every operational value is config, never a
constant buried in the provider, and the model id lives here rather than in
``domain/`` (plan §1, §2.10, `PROJECT.md` §13).

The API key is deliberately *absent*. It is a secret, so it is passed in at
construction from ``Settings`` and never stored on an object that something
might serialise into a research snapshot or a log line.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class OpenAIConfig(BaseModel):
    """Model, timeout, retry and token settings for :class:`OpenAIProvider`."""

    model: str = "gpt-5.6-luna"
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    max_retries: int = Field(default=3, ge=0)
    max_output_tokens: int = Field(default=8192, gt=0)
    base_url: str | None = None
    """Override the API host — for a gateway or a proxy. ``None`` uses OpenAI's."""
