"""Provider selection (plan §9, §10 Phase 7.5).

Plan §9 makes ``FakeLLMProvider`` the default and requires ``LLM_PROVIDER``
to be set explicitly before anything reaches OpenAI, "so no test run can
bill an account by accident". That default lives here, in the one function
that decides which implementation a process gets.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import SecretStr

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.ai.openai import OpenAIConfig, OpenAIProvider
from tripfinder.domain.ports import LLMProvider
from tripfinder.domain.usage import TokenLedger


class LLMProviderName(StrEnum):
    """The implementations ``LLM_PROVIDER`` can select."""

    FAKE = "fake"
    OPENAI = "openai"


DEFAULT_LLM_PROVIDER = LLMProviderName.FAKE


def build_llm_provider(
    provider: LLMProviderName = DEFAULT_LLM_PROVIDER,
    *,
    openai_api_key: SecretStr | None = None,
    openai_config: OpenAIConfig | None = None,
    ledger: TokenLedger | None = None,
) -> LLMProvider:
    """The provider this process should use.

    A missing key is *not* rejected here. Phase 7.5's acceptance requires
    that failure to surface as a failed research with a named reason, not as
    a process that would not start — so the provider is built either way and
    the first call is what fails.

    ``ledger`` is where the run's token spend accumulates (plan §2.15).
    Every implementation takes one, including the fake — what a run costs
    must not be a number that only exists in production, or the code that
    reads it is never exercised.
    """
    if provider is LLMProviderName.FAKE:
        return FakeLLMProvider(ledger=ledger)
    return OpenAIProvider(openai_config, api_key=openai_api_key, ledger=ledger)
