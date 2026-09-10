"""The runtime settings layer (plan §2.9, §10 Phase 7.5 acceptance).

Two obligations meet here. ``LLM_PROVIDER`` defaults to ``fake``, so no test
run or CI job can reach a paid model by accident (plan §9); and
``OPENAI_API_KEY`` is a secret, which means it must be impossible to print,
log, or serialise by accident.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from tripfinder.ai.factory import LLMProviderName
from tripfinder.persistence.database import DEFAULT_DATABASE_URL
from tripfinder.settings import DEFAULT_FRONTEND_URL, Settings

A_KEY = "sk-not-a-real-key-1234567890"


class TestDefaults:
    def test_an_empty_environment_yields_the_documented_defaults(self) -> None:
        settings = Settings.from_env({})

        assert settings.database_url == DEFAULT_DATABASE_URL
        assert settings.frontend_url == DEFAULT_FRONTEND_URL
        assert settings.llm_provider is LLMProviderName.FAKE
        assert settings.openai_api_key is None

    def test_the_default_provider_is_fake_even_when_a_key_is_present(self) -> None:
        """A key in the environment is not consent to spend it (plan §9)."""
        settings = Settings.from_env({"OPENAI_API_KEY": A_KEY})

        assert settings.llm_provider is LLMProviderName.FAKE


class TestReadingTheEnvironment:
    def test_every_value_comes_from_the_environment(self) -> None:
        settings = Settings.from_env(
            {
                "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/x",
                "FRONTEND_URL": "https://tripfinder.example.test",
                "LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": A_KEY,
            }
        )

        assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/x"
        assert settings.frontend_url == "https://tripfinder.example.test"
        assert settings.llm_provider is LLMProviderName.OPENAI
        assert settings.openai_api_key is not None
        assert settings.openai_api_key.get_secret_value() == A_KEY

    @pytest.mark.parametrize("value", ["", "   "])
    def test_a_blank_key_is_read_as_absent(self, value: str) -> None:
        """`.env.example` ships `OPENAI_API_KEY=` — that must mean unset, not empty."""
        settings = Settings.from_env({"OPENAI_API_KEY": value})

        assert settings.openai_api_key is None

    def test_a_blank_provider_falls_back_to_the_default(self) -> None:
        settings = Settings.from_env({"LLM_PROVIDER": ""})

        assert settings.llm_provider is LLMProviderName.FAKE

    def test_an_unknown_provider_is_an_error_not_a_silent_fallback(self) -> None:
        """A typo that quietly selected `fake` would report fixtures as findings."""
        with pytest.raises(ValueError) as caught:
            Settings.from_env({"LLM_PROVIDER": "opeani"})

        assert "opeani" in str(caught.value)
        assert "openai" in str(caught.value)

    def test_reads_the_process_environment_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", A_KEY)

        settings = Settings.from_env()

        assert settings.llm_provider is LLMProviderName.OPENAI
        assert settings.openai_api_key is not None


class TestTheKeyIsNeverLoggedOrPersisted:
    """Plan §10 Phase 7.5: "the key is never logged or persisted"."""

    def test_repr_does_not_reveal_it(self) -> None:
        settings = Settings.from_env({"OPENAI_API_KEY": A_KEY})

        assert A_KEY not in repr(settings)
        assert A_KEY not in str(settings)

    def test_json_serialisation_does_not_reveal_it(self) -> None:
        settings = Settings.from_env({"OPENAI_API_KEY": A_KEY})

        assert A_KEY not in settings.model_dump_json()

    def test_only_an_explicit_unwrap_reveals_it(self) -> None:
        settings = Settings.from_env({"OPENAI_API_KEY": A_KEY})

        assert settings.openai_api_key == SecretStr(A_KEY)
        assert settings.openai_api_key is not None
        assert settings.openai_api_key.get_secret_value() == A_KEY
