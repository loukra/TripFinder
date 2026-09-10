"""The OpenAI adapter (plan §10 Phase 7.5).

Two things are under test. The first is ordinary: the provider satisfies
``LLMProvider`` and returns a validated response model. The second is plan
§0.1's — *every* way this call can go wrong raises, loudly, with a named
cause. A provider that degraded quietly would hand the pipeline an empty
analysis, and an empty analysis is indistinguishable from a question nobody
had an opinion about.

No test here touches the network: the SDK client is driven through a mock
transport (see ``conftest.py``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel, SecretStr

from builders.openai_responses import (
    refusal_response_body,
    response_body,
    truncated_response_body,
)
from tripfinder.ai.errors import (
    LLMCredentialError,
    LLMProviderError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)
from tripfinder.ai.openai import OpenAIConfig, OpenAIProvider
from tripfinder.domain.models import FailureKind
from tripfinder.domain.ports import LLMProvider

Handler = Callable[[httpx2.Request], httpx2.Response]
ProviderFor = Callable[..., OpenAIProvider]
JsonHandler = Callable[..., Handler]
FastConfig = Callable[..., OpenAIConfig]


class Verdict(BaseModel):
    """A minimal stand-in for a real analysis schema."""

    verdict: str
    confidence: float


def _answering(payload: dict[str, Any]) -> Handler:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=response_body(payload))

    return handler


class TestTheHappyPath:
    def test_satisfies_the_llm_provider_port(self) -> None:
        assert isinstance(OpenAIProvider(), LLMProvider)

    async def test_returns_the_validated_response_model(self, provider_for: ProviderFor) -> None:
        provider = provider_for(_answering({"verdict": "polling", "confidence": 0.9}))

        result = await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert result == Verdict(verdict="polling", confidence=0.9)

    async def test_sends_the_configured_model_prompt_and_token_cap(
        self, provider_for: ProviderFor, json_handler: JsonHandler, fast_config: FastConfig
    ) -> None:
        """Plan §10 Phase 7.5: the model id is config, never a constant in the call."""
        seen: list[httpx2.Request] = []
        provider = provider_for(
            json_handler(200, response_body({"verdict": "topical", "confidence": 0.1}), seen=seen),
            config=fast_config(model="gpt-5-nano", max_output_tokens=321),
        )

        await provider.complete_structured(prompt="classify this", response_model=Verdict)

        body = json.loads(seen[0].content)
        assert body["model"] == "gpt-5-nano"
        assert body["max_output_tokens"] == 321
        assert body["input"] == "classify this"

    async def test_asks_for_the_response_model_as_a_strict_schema(
        self, provider_for: ProviderFor, json_handler: JsonHandler, fast_config: FastConfig
    ) -> None:
        """`PROJECT.md` demands validated structured output, not free text to parse."""
        seen: list[httpx2.Request] = []
        provider = provider_for(
            json_handler(200, response_body({"verdict": "polling", "confidence": 0.5}), seen=seen),
            config=fast_config(),
        )

        await provider.complete_structured(prompt="classify", response_model=Verdict)

        text_format = json.loads(seen[0].content)["text"]["format"]
        assert text_format["type"] == "json_schema"
        assert text_format["strict"] is True
        assert text_format["name"] == "Verdict"
        assert set(text_format["schema"]["required"]) == {"verdict", "confidence"}


class TestACredentialProblemFailsLoudly:
    """Plan §10 Phase 7.5: missing *or* rejected — both must fail the research."""

    async def test_a_missing_key_raises_before_any_request_is_made(
        self, fast_config: FastConfig
    ) -> None:
        provider = OpenAIProvider(fast_config(), api_key=None)

        with pytest.raises(LLMCredentialError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_CREDENTIAL
        assert "OPENAI_API_KEY" in str(caught.value)

    async def test_an_empty_key_is_the_same_as_a_missing_one(
        self, fast_config: FastConfig
    ) -> None:
        provider = OpenAIProvider(fast_config(), api_key=SecretStr(""))

        with pytest.raises(LLMCredentialError):
            await provider.complete_structured(prompt="classify", response_model=Verdict)

    @pytest.mark.parametrize("status_code", [401, 403])
    async def test_a_rejected_key_raises_the_same_error_as_a_missing_one(
        self,
        provider_for: ProviderFor,
        json_handler: JsonHandler,
        fast_config: FastConfig,
        status_code: int,
    ) -> None:
        provider = provider_for(
            json_handler(status_code, {"error": {"message": "invalid key"}}),
            config=fast_config(),
        )

        with pytest.raises(LLMCredentialError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_CREDENTIAL

    async def test_the_error_never_repeats_the_key(
        self, provider_for: ProviderFor, json_handler: JsonHandler, fast_config: FastConfig
    ) -> None:
        """A secret in an error message is a secret in the persisted snapshot."""
        provider = provider_for(
            json_handler(401, {"error": {"message": "invalid key"}}), config=fast_config()
        )

        with pytest.raises(LLMCredentialError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert "test-key-not-a-real-credential" not in str(caught.value)


class TestAnUnreachableProviderFailsLoudly:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    async def test_a_transient_status_raises_unavailable(
        self,
        provider_for: ProviderFor,
        json_handler: JsonHandler,
        fast_config: FastConfig,
        status_code: int,
    ) -> None:
        provider = provider_for(
            json_handler(status_code, {"error": {"message": "busy"}}), config=fast_config()
        )

        with pytest.raises(LLMUnavailableError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_UNAVAILABLE

    @pytest.mark.parametrize(
        "error",
        [httpx2.ConnectTimeout("timed out"), httpx2.ConnectError("connection refused")],
        ids=["timeout", "connection refused"],
    )
    async def test_a_transport_failure_raises_unavailable(
        self,
        provider_for: ProviderFor,
        raising_handler: Callable[[Exception], Handler],
        fast_config: FastConfig,
        error: Exception,
    ) -> None:
        provider = provider_for(raising_handler(error), config=fast_config())

        with pytest.raises(LLMUnavailableError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_UNAVAILABLE

    async def test_max_retries_is_config_and_is_honoured(
        self, provider_for: ProviderFor, json_handler: JsonHandler, fast_config: FastConfig
    ) -> None:
        """Retry policy is `OpenAIConfig`'s, exactly as it is `ArcticShiftConfig`'s."""
        seen: list[httpx2.Request] = []
        provider = provider_for(
            json_handler(500, {"error": {"message": "boom"}}, seen=seen),
            config=fast_config(max_retries=2),
        )

        with pytest.raises(LLMUnavailableError):
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert len(seen) == 3  # the first attempt, plus two retries


class TestARejectedRequestIsOurBugNotAnOutage:
    async def test_a_4xx_raises_request_rejected(
        self, provider_for: ProviderFor, json_handler: JsonHandler, fast_config: FastConfig
    ) -> None:
        provider = provider_for(
            json_handler(400, {"error": {"message": "unknown model"}}), config=fast_config()
        )

        with pytest.raises(LLMRequestRejectedError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_REQUEST_REJECTED

    async def test_a_rejected_request_is_not_retried(
        self, provider_for: ProviderFor, json_handler: JsonHandler, fast_config: FastConfig
    ) -> None:
        seen: list[httpx2.Request] = []
        provider = provider_for(
            json_handler(400, {"error": {"message": "unknown model"}}, seen=seen),
            config=fast_config(max_retries=3),
        )

        with pytest.raises(LLMRequestRejectedError):
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert len(seen) == 1


class TestAnUnusableAnswerIsNeverCoerced:
    """`PROJECT.md` §29: never silently invent evidence — not even by omission."""

    async def test_a_truncated_response_raises_and_names_the_cause(
        self, provider_for: ProviderFor, json_handler: JsonHandler, fast_config: FastConfig
    ) -> None:
        provider = provider_for(
            json_handler(200, truncated_response_body()), config=fast_config()
        )

        with pytest.raises(LLMResponseError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_INVALID_RESPONSE
        assert "cut short" in str(caught.value)
        assert "max_output_tokens" in str(caught.value)

    async def test_a_refusal_raises_and_quotes_it(
        self, provider_for: ProviderFor, json_handler: JsonHandler, fast_config: FastConfig
    ) -> None:
        provider = provider_for(
            json_handler(200, refusal_response_body()), config=fast_config()
        )

        with pytest.raises(LLMResponseError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert "refused" in str(caught.value)
        assert "I will not answer that." in str(caught.value)

    async def test_an_answer_missing_a_field_raises_rather_than_half_filling_the_model(
        self, provider_for: ProviderFor, fast_config: FastConfig
    ) -> None:
        provider = provider_for(_answering({"verdict": "polling"}), config=fast_config())

        with pytest.raises(LLMResponseError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_INVALID_RESPONSE
        assert "Verdict" in str(caught.value)


class TestEveryFailureNamesItsKind:
    def test_all_provider_errors_carry_a_failure_kind(self) -> None:
        """The pipeline reads `.kind` off whatever it catches — none may lack one."""
        errors: list[LLMProviderError] = [
            LLMCredentialError("no key"),
            LLMUnavailableError("timeout"),
            LLMRequestRejectedError("bad model"),
            LLMResponseError("refused"),
        ]

        assert {error.kind for error in errors} == set(FailureKind)
