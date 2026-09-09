"""Typed failures for the Arctic Shift adapter.

Kept local to ``sources/`` — the domain layer never sees these (plan §3.1's
import boundary).
"""

from __future__ import annotations


class ArcticShiftError(Exception):
    """Base class for all Arctic Shift adapter errors."""


class ArcticShiftRequestError(ArcticShiftError):
    """The request itself was rejected (HTTP 4xx other than 429). Never retried."""


class ArcticShiftUnavailableError(ArcticShiftError):
    """Retries were exhausted without a usable response.

    ``kind`` reuses the ``failure_kinds`` vocabulary plan §8.1 defines for
    ``SourceHealth`` (``timeout | rate_limited | http_5xx | malformed | network``)
    so a later health-accounting step can consume it without translation.
    """

    def __init__(self, *, kind: str, message: str, attempts: int) -> None:
        super().__init__(
            f"arctic shift unavailable after {attempts} attempt(s) ({kind}): {message}"
        )
        self.kind = kind
        self.attempts = attempts
