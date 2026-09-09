"""Shared cassette-loading fixtures for Arctic Shift tests (plan §9).

Exposed as fixtures (not plain imports) so test modules need no relative
imports — this test tree, like the rest of the suite, has no ``__init__.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

_FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "arctic_shift"


@pytest.fixture
def load_fixture() -> Callable[[str], dict[str, Any]]:
    def _load(name: str) -> dict[str, Any]:
        return cast("dict[str, Any]", json.loads((_FIXTURES_DIR / name).read_text()))

    return _load


@pytest.fixture
def fast_config() -> Callable[..., dict[str, Any]]:
    """Config overrides that keep retry/backoff/throttle tests fast and deterministic."""

    def _fast_config(**overrides: Any) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "max_retries": 2,
            "backoff_base_seconds": 0.001,
            "requests_per_second": 1000.0,
            "timeout_seconds": 5.0,
            "health_check_timeout_seconds": 5.0,
        }
        defaults.update(overrides)
        return defaults

    return _fast_config
