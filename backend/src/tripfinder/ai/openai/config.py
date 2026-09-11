"""Configuration for the OpenAI provider (plan §10 Phase 7.5).

Follows ``ArcticShiftConfig``: every operational value is config, never a
constant buried in the provider, and the model id lives here rather than in
``domain/`` (plan §1, §2.10, `PROJECT.md` §13).

The API key is deliberately *absent*. It is a secret, so it is passed in at
construction from ``Settings`` and never stored on an object that something
might serialise into a research snapshot or a log line.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ReasoningEffort(StrEnum):
    """How much the model is asked to think before answering (plan §2.10, §2.12).

    Measured on one real 20-comment analysis batch, 20/20 comments analysed
    at every level: default 32.7 s, ``LOW`` 23.2 s, ``NONE`` 20.7 s. A
    smaller lever than it looks, but comment analysis was 93 % of a run's
    wall clock, so a third off each of 50 calls is not nothing.

    ``NONE`` is deliberately not the default. The step it governs is the one
    judgement in the pipeline that has to weigh what a comment *means*
    against a question it never saw (plan §5), and buying 2.5 s per batch by
    taking away the thinking is the kind of trade Phase 15 should make on
    evidence, not one to assume up front.

    ``MINIMAL`` is the default from 14.8, for the 60-second target (§2.14.1)
    — one step down from ``LOW`` rather than the whole way to ``NONE``, so
    the judgement above keeps some thinking behind it. The measurements
    above say what this is worth: roughly 2 s per call, not a halving. It is
    a small lever pulled because the target needs every one of them, and
    Phase 15 owns whether the analysis quality paid for it.
    """

    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OpenAIConfig(BaseModel):
    """Model, timeout, retry and token settings for :class:`OpenAIProvider`."""

    model: str = "gpt-5.6-luna"
    reasoning_effort: ReasoningEffort | None = ReasoningEffort.MINIMAL
    """``None`` sends no reasoning parameter at all — the model's own default."""

    timeout_seconds: float = Field(default=60.0, gt=0.0)
    max_retries: int = Field(default=3, ge=0)
    max_output_tokens: int = Field(default=8192, gt=0)
    base_url: str | None = None
    """Override the API host — for a gateway or a proxy. ``None`` uses OpenAI's."""
