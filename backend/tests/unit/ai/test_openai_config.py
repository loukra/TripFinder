"""`OpenAIConfig` (plan §10 Phase 7.5 acceptance).

The point of the file: model ids, timeouts, retries and token caps are
configuration, and the API key is not part of it.
"""

from __future__ import annotations

from tripfinder.ai.openai import OpenAIConfig


def test_defaults_match_the_plan_2_10_model_choice() -> None:
    config = OpenAIConfig()

    assert config.model == "gpt-5.6-luna"
    assert config.max_retries == 3
    assert config.base_url is None


def test_every_field_is_overridable() -> None:
    config = OpenAIConfig(
        model="gpt-5",
        timeout_seconds=5.0,
        max_retries=0,
        max_output_tokens=256,
        base_url="https://gateway.example.test/v1",
    )

    assert config.model == "gpt-5"
    assert config.timeout_seconds == 5.0
    assert config.max_retries == 0
    assert config.max_output_tokens == 256
    assert config.base_url == "https://gateway.example.test/v1"


def test_the_config_holds_no_credential() -> None:
    """A secret on a serialisable config object is a secret in a log line.

    The key is passed to the provider separately, from ``Settings``.
    """
    fields = set(OpenAIConfig.model_fields)

    assert not {field for field in fields if "key" in field or "secret" in field}


def test_no_model_id_is_hardcoded_in_the_domain_layer() -> None:
    """`PROJECT.md` §13: model ids live in config, never in `domain/`."""
    from pathlib import Path

    domain = Path(__file__).resolve().parents[3] / "src" / "tripfinder" / "domain"
    sources = "\n".join(path.read_text() for path in domain.rglob("*.py"))

    assert "gpt-" not in sources
