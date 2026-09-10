"""Provider selection (plan §9, §10 Phase 7.5 acceptance).

The load-bearing assertion is the first one: the default is ``fake``, so a
test run or a CI job can never bill an account by accident.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from tripfinder.ai.factory import DEFAULT_LLM_PROVIDER, LLMProviderName, build_llm_provider
from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.ai.openai import OpenAIConfig, OpenAIProvider
from tripfinder.domain.ports import LLMProvider


def test_the_default_provider_is_fake() -> None:
    assert DEFAULT_LLM_PROVIDER is LLMProviderName.FAKE
    assert isinstance(build_llm_provider(), FakeLLMProvider)


def test_fake_is_selected_explicitly_too() -> None:
    assert isinstance(build_llm_provider(LLMProviderName.FAKE), FakeLLMProvider)


def test_openai_is_selected_only_when_asked_for() -> None:
    provider = build_llm_provider(
        LLMProviderName.OPENAI, openai_api_key=SecretStr("sk-test")
    )

    assert isinstance(provider, OpenAIProvider)


def test_openai_config_is_passed_through() -> None:
    config = OpenAIConfig(model="gpt-5")

    provider = build_llm_provider(
        LLMProviderName.OPENAI, openai_api_key=SecretStr("sk-test"), openai_config=config
    )

    assert isinstance(provider, OpenAIProvider)


@pytest.mark.parametrize("name", list(LLMProviderName))
def test_every_selectable_provider_satisfies_the_port(name: LLMProviderName) -> None:
    assert isinstance(build_llm_provider(name, openai_api_key=SecretStr("sk-test")), LLMProvider)


def test_a_missing_key_is_not_rejected_at_construction() -> None:
    """Phase 7.5 acceptance: a missing credential fails the *research*, with a reason.

    A factory that refused to build would turn it into a process that will
    not start — a stack trace in a log, where the user needs a research that
    says why it found nothing.
    """
    provider = build_llm_provider(LLMProviderName.OPENAI, openai_api_key=None)

    assert isinstance(provider, OpenAIProvider)
