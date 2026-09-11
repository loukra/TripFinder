"""Classifying adapter failures into §8.1's ``failure_kinds`` vocabulary.

Lives in ``sources/`` because it is a fact about adapters, and is consumed
by ``pipeline/`` health accounting and by ``search/`` — never the other way
round. It reads the label off the exception rather than matching types, so
it classifies a ``WebSearchError`` exactly as it classifies an
``ArcticShiftUnavailableError``, without knowing either exists.
"""

from __future__ import annotations

UNKNOWN_FAILURE_KIND = "unknown"


def failure_kind(error: BaseException) -> str:
    """The §8.1 ``failure_kinds`` label for an adapter exception.

    Read off the exception rather than matched against adapter-specific
    types, so nothing here has to know which adapter raised it. Adapters
    that classify their own failures (``ArcticShiftUnavailableError`` carries
    ``kind``) are reported precisely; anything else is ``unknown``, which
    still counts as a failure and still degrades the run.
    """
    kind = getattr(error, "kind", None)
    return kind if isinstance(kind, str) and kind else UNKNOWN_FAILURE_KIND
