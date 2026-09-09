"""Arctic Shift SourceAdapter — the MVP's only source (plan §1, §8)."""

from __future__ import annotations

from tripfinder.sources.arctic_shift.adapter import ArcticShiftAdapter
from tripfinder.sources.arctic_shift.config import ArcticShiftConfig
from tripfinder.sources.arctic_shift.errors import (
    ArcticShiftError,
    ArcticShiftRequestError,
    ArcticShiftUnavailableError,
)

__all__ = [
    "ArcticShiftAdapter",
    "ArcticShiftConfig",
    "ArcticShiftError",
    "ArcticShiftRequestError",
    "ArcticShiftUnavailableError",
]
