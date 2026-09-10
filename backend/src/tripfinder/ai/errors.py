"""Typed failures every ``LLMProvider`` implementation raises (plan §0.1, §10 Phase 7.5).

Shared rather than vendor-local — unlike ``sources/``, where each adapter
owns its errors and ``sources/failures.py`` classifies them afterwards. The
pipeline has to react to an LLM failure the same way whichever provider
raised it, so the vocabulary is defined once, here, and each provider maps
its own exceptions onto it.

Every one of these carries a :class:`FailureKind`, because §0.1 forbids the
alternative: a provider that swallowed an error and returned an empty model
would hand the pipeline an empty analysis, and an empty analysis is
indistinguishable from a query nobody had an opinion about.
"""

from __future__ import annotations

from typing import ClassVar

from tripfinder.domain.models import FailureKind


class LLMProviderError(Exception):
    """An LLM call did not produce a usable answer.

    Never raised directly — each subclass below fixes ``kind``, so the
    pipeline can always name the cause without inspecting the message.
    """

    kind: ClassVar[FailureKind]


class LLMCredentialError(LLMProviderError):
    """No credential was configured, or the provider rejected the one that was.

    The two cases are one failure: in both, the run has no access to a model
    and nothing downstream can proceed.
    """

    kind = FailureKind.LLM_CREDENTIAL


class LLMUnavailableError(LLMProviderError):
    """The provider could not be reached, or refused to serve, after retries.

    Timeouts, rate limits, connection failures and 5xx — transient by
    nature, and retried inside the provider before this is raised.
    """

    kind = FailureKind.LLM_UNAVAILABLE


class LLMRequestRejectedError(LLMProviderError):
    """The provider rejected the request itself (a 4xx retrying cannot fix).

    Our bug, not an outage: a malformed schema, an unknown model, a request
    over a hard limit.
    """

    kind = FailureKind.LLM_REQUEST_REJECTED


class LLMResponseError(LLMProviderError):
    """The call succeeded but produced nothing usable.

    A refusal, a response truncated at the token cap, or output that did not
    validate against the requested model. Coercing any of these into a
    partial answer is exactly the fabrication `PROJECT.md` §29 forbids.
    """

    kind = FailureKind.LLM_INVALID_RESPONSE
