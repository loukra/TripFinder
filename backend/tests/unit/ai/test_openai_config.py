"""`OpenAIConfig` (plan §10 Phase 7.5 acceptance).

The point of the file: model ids, timeouts, retries and token caps are
configuration, and the API key is not part of it.
"""

from __future__ import annotations

from tripfinder.ai.openai import OpenAIConfig
from tripfinder.ai.openai.config import ReasoningEffort


def test_defaults_match_the_plan_2_10_model_choice() -> None:
    config = OpenAIConfig()

    assert config.model == "gpt-5.6-luna"
    assert config.max_retries == 3
    assert config.base_url is None
    assert config.reasoning_effort is ReasoningEffort.LOW


def test_every_field_is_overridable() -> None:
    config = OpenAIConfig(
        model="gpt-5",
        reasoning_effort=ReasoningEffort.HIGH,
        timeout_seconds=5.0,
        max_retries=0,
        max_output_tokens=256,
        base_url="https://gateway.example.test/v1",
    )

    assert config.model == "gpt-5"
    assert config.reasoning_effort is ReasoningEffort.HIGH
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


def test_no_model_parameter_is_hardcoded_outside_this_config() -> None:
    """Plan §2.12/§2.10: the call sends what the config says, and nothing else.

    ``reasoning.effort`` is the parameter this is about — Phase 8 left it at
    the model's default and §2.10 had already asked the first phase calling
    the provider to choose deliberately — but the rule is general, so the
    assertion is against the provider module rather than one field of it.
    """
    from pathlib import Path

    provider = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "tripfinder"
        / "ai"
        / "openai"
        / "provider.py"
    )
    source = provider.read_text()

    for effort in ReasoningEffort:
        assert f'"{effort.value}"' not in source
    assert "gpt-" not in source
