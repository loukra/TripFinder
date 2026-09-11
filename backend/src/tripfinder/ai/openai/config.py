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

    **``MINIMAL`` is in this enum but ``gpt-5.6-luna`` does not accept it.**
    Setting it as the default cost a real run, which died at the first model
    call with ``HTTP 400: 'minimal' is not supported with the
    'gpt-5.6-luna' model. Supported values are: 'none', 'low', 'medium',
    'high', 'xhigh', and 'max'``. The enum spans what the *provider* offers
    across models; what a given model accepts is narrower, and the only
    place that shows up is a request. The value stays for models that take
    it.

    ``NONE`` is the default from 14.8, for the 60-second target (§2.14.1):
    the nearest step below ``LOW`` this model actually has. The measurements
    above say what it is worth — 20.7 s against 23.2 s, roughly 2 s a call,
    not a halving — so it is a small lever pulled because the target needs
    every one of them. The caution above stands and is now a live debt:
    analysis is the pipeline's one act of judgement, and Phase 15 owns
    whether taking the thinking away cost accuracy.
    """

    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OpenAIConfig(BaseModel):
    """Model, timeout, retry and token settings for :class:`OpenAIProvider`."""

    model: str = "gpt-5.6-luna"
    reasoning_effort: ReasoningEffort | None = ReasoningEffort.NONE
    """``None`` sends no reasoning parameter at all — the model's own default."""

    timeout_seconds: float = Field(default=60.0, gt=0.0)
    max_retries: int = Field(default=3, ge=0)
    max_output_tokens: int = Field(default=8192, gt=0)
    base_url: str | None = None
    """Override the API host — for a gateway or a proxy. ``None`` uses OpenAI's."""
