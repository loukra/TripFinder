"""Typed failures every ``WebSearchProvider`` implementation raises (plan §2.11).

Shared across providers rather than vendor-local, for the same reason
``ai/errors.py`` is: discovery has to react to a dead search engine the same
way whichever engine it was.

``kind`` reuses the §8.1 ``failure_kinds`` vocabulary
(``timeout | rate_limited | http_5xx | malformed | network | credential``) so
health accounting consumes it without translation — which is what keeps
"search was down" from reaching the user as "Reddit had nothing to say".
"""

from __future__ import annotations


class WebSearchError(Exception):
    """Base class for every web search provider failure."""

    kind = "unknown"


class WebSearchCredentialError(WebSearchError):
    """No API key was configured, or the provider rejected the one that was."""

    kind = "credential"


class WebSearchRequestError(WebSearchError):
    """The request itself was rejected (a 4xx retrying cannot fix). Our bug."""

    kind = "request_rejected"


class WebSearchUnavailableError(WebSearchError):
    """Retries were exhausted without a usable response."""

    def __init__(self, *, kind: str, message: str, attempts: int) -> None:
        super().__init__(f"web search unavailable after {attempts} attempt(s) ({kind}): {message}")
        self.kind = kind
        self.attempts = attempts
