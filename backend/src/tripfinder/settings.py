"""Runtime settings — the one place the environment enters this process.

Plan §2.9: until Phase 7.5 there was nowhere to put an API key, so
``main.py`` and ``worker.py`` each read ``os.environ`` for themselves. Every
environment-provided value is now read here, once, and passed downward
explicitly.

``OPENAI_API_KEY`` and ``SERPER_API_KEY`` are secrets, so they are held as
``SecretStr``: they cannot be printed, logged, or serialised into a research
snapshot by accident. `PROJECT.md` §29 keeps secrets out of source control;
this keeps them out of the record too.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, SecretStr

from tripfinder.ai.factory import DEFAULT_LLM_PROVIDER, LLMProviderName
from tripfinder.persistence.database import DEFAULT_DATABASE_URL
from tripfinder.search.factory import DEFAULT_SEARCH_PROVIDER, SearchProviderName

DEFAULT_FRONTEND_URL = "http://localhost:3000"


class Settings(BaseModel):
    """Everything this process reads from its environment."""

    database_url: str = DEFAULT_DATABASE_URL
    frontend_url: str = DEFAULT_FRONTEND_URL
    llm_provider: LLMProviderName = DEFAULT_LLM_PROVIDER
    openai_api_key: SecretStr | None = None
    search_provider: SearchProviderName = DEFAULT_SEARCH_PROVIDER
    serper_api_key: SecretStr | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Read settings from ``environ``, defaulting to the process environment."""
        env = os.environ if environ is None else environ
        return cls(
            database_url=env.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            frontend_url=env.get("FRONTEND_URL", DEFAULT_FRONTEND_URL),
            llm_provider=_read_llm_provider(env),
            openai_api_key=_read_secret(env, "OPENAI_API_KEY"),
            search_provider=_read_search_provider(env),
            serper_api_key=_read_secret(env, "SERPER_API_KEY"),
        )


def _read_llm_provider(env: Mapping[str, str]) -> LLMProviderName:
    """``LLM_PROVIDER``, or the plan §9 default.

    An unrecognised value is an error rather than a silent fall back to
    ``fake``: a run that quietly used canned answers because of a typo would
    report fixture data as findings.
    """
    raw = env.get("LLM_PROVIDER", "").strip() or DEFAULT_LLM_PROVIDER.value
    try:
        return LLMProviderName(raw)
    except ValueError as exc:
        allowed = ", ".join(name.value for name in LLMProviderName)
        raise ValueError(f"LLM_PROVIDER must be one of: {allowed}. Got {raw!r}") from exc


def _read_search_provider(env: Mapping[str, str]) -> SearchProviderName:
    """``SEARCH_PROVIDER``, or the plan §2.11 default. Typos are errors, as above."""
    raw = env.get("SEARCH_PROVIDER", "").strip() or DEFAULT_SEARCH_PROVIDER.value
    try:
        return SearchProviderName(raw)
    except ValueError as exc:
        allowed = ", ".join(name.value for name in SearchProviderName)
        raise ValueError(f"SEARCH_PROVIDER must be one of: {allowed}. Got {raw!r}") from exc


def _read_secret(env: Mapping[str, str], name: str) -> SecretStr | None:
    """A secret from the environment. Unset and empty mean the same thing: absent."""
    value = env.get(name, "").strip()
    return SecretStr(value) if value else None
