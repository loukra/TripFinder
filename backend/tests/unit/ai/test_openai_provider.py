"""The OpenAI adapter (plan §10 Phase 7.5).

Two things are under test. The first is ordinary: the provider satisfies
``LLMProvider`` and returns a validated response model. The second is plan
§0.1's — *every* way this call can go wrong raises, loudly, with a named
cause. A provider that degraded quietly would hand the pipeline an empty
analysis, and an empty analysis is indistinguishable from a question nobody
had an opinion about.

No test here touches the network: the SDK client is driven through a mock
transport (see ``builders/openai_provider.py``).
"""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel, SecretStr

from builders.openai_provider import (
    STUB_API_KEY,
    Handler,
    fast_config,
    json_handler,
    raising_handler,
    stubbed_provider,
)
from builders.openai_responses import (
    refusal_response_body,
    response_body,
    truncated_response_body,
    usage,
)
from tripfinder.ai.errors import (
    LLMCredentialError,
    LLMProviderError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)
from tripfinder.ai.openai import OpenAIProvider
from tripfinder.ai.openai.config import OpenAIConfig, ReasoningEffort
from tripfinder.domain.models import FailureKind
from tripfinder.domain.ports import LLMProvider
from tripfinder.domain.usage import TokenLedger


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

    async def test_returns_the_validated_response_model(self) -> None:
        provider = stubbed_provider(_answering({"verdict": "polling", "confidence": 0.9}))

        result = await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert result == Verdict(verdict="polling", confidence=0.9)

    async def test_sends_the_configured_model_prompt_and_token_cap(self) -> None:
        """Plan §10 Phase 7.5: the model id is config, never a constant in the call."""
        seen: list[httpx2.Request] = []
        provider = stubbed_provider(
            json_handler(200, response_body({"verdict": "topical", "confidence": 0.1}), seen=seen),
            config=fast_config(model="gpt-5-nano", max_output_tokens=321),
        )

        await provider.complete_structured(prompt="classify this", response_model=Verdict)

        body = json.loads(seen[0].content)
        assert body["model"] == "gpt-5-nano"
        assert body["max_output_tokens"] == 321
        assert body["input"] == "classify this"

    async def test_sends_the_configured_reasoning_effort(self) -> None:
        """Plan §2.10/§2.12: the effort is set deliberately, not inherited."""
        seen: list[httpx2.Request] = []
        provider = stubbed_provider(
            json_handler(200, response_body({"verdict": "polling", "confidence": 0.5}), seen=seen),
            config=fast_config(reasoning_effort=ReasoningEffort.LOW),
        )

        await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert json.loads(seen[0].content)["reasoning"] == {"effort": "low"}

    async def test_the_default_effort_is_low(self) -> None:
        """The measured 23.2 s against a default of 32.7 s, per batch, 50 batches."""
        assert OpenAIConfig().reasoning_effort is ReasoningEffort.NONE

    async def test_no_configured_effort_sends_no_reasoning_parameter(self) -> None:
        """Omitting the field and asking for "none" are different requests."""
        seen: list[httpx2.Request] = []
        provider = stubbed_provider(
            json_handler(200, response_body({"verdict": "polling", "confidence": 0.5}), seen=seen),
            config=fast_config(reasoning_effort=None),
        )

        await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert "reasoning" not in json.loads(seen[0].content)

    async def test_asks_for_the_response_model_as_a_strict_schema(self) -> None:
        """`PROJECT.md` demands validated structured output, not free text to parse."""
        seen: list[httpx2.Request] = []
        provider = stubbed_provider(
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

    async def test_a_missing_key_raises_before_any_request_is_made(self) -> None:
        provider = OpenAIProvider(fast_config(), api_key=None)

        with pytest.raises(LLMCredentialError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_CREDENTIAL
        assert "OPENAI_API_KEY" in str(caught.value)

    async def test_an_empty_key_is_the_same_as_a_missing_one(self) -> None:
        provider = OpenAIProvider(fast_config(), api_key=SecretStr(""))

        with pytest.raises(LLMCredentialError):
            await provider.complete_structured(prompt="classify", response_model=Verdict)

    @pytest.mark.parametrize("status_code", [401, 403])
    async def test_a_rejected_key_raises_the_same_error_as_a_missing_one(
        self, status_code: int
    ) -> None:
        provider = stubbed_provider(
            json_handler(status_code, {"error": {"message": "invalid key"}}),
            config=fast_config(),
        )

        with pytest.raises(LLMCredentialError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_CREDENTIAL

    async def test_the_error_never_repeats_the_key(self) -> None:
        """A secret in an error message is a secret in the persisted snapshot."""
        provider = stubbed_provider(
            json_handler(401, {"error": {"message": "invalid key"}}), config=fast_config()
        )

        with pytest.raises(LLMCredentialError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert STUB_API_KEY not in str(caught.value)


class TestAnUnreachableProviderFailsLoudly:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    async def test_a_transient_status_raises_unavailable(self, status_code: int) -> None:
        provider = stubbed_provider(
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
    async def test_a_transport_failure_raises_unavailable(self, error: Exception) -> None:
        provider = stubbed_provider(raising_handler(error), config=fast_config())

        with pytest.raises(LLMUnavailableError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_UNAVAILABLE

    async def test_max_retries_is_config_and_is_honoured(self) -> None:
        """Retry policy is `OpenAIConfig`'s, exactly as it is `ArcticShiftConfig`'s."""
        seen: list[httpx2.Request] = []
        provider = stubbed_provider(
            json_handler(500, {"error": {"message": "boom"}}, seen=seen),
            config=fast_config(max_retries=2),
        )

        with pytest.raises(LLMUnavailableError):
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert len(seen) == 3  # the first attempt, plus two retries


class TestARejectedRequestIsOurBugNotAnOutage:
    async def test_a_4xx_raises_request_rejected(self) -> None:
        provider = stubbed_provider(
            json_handler(400, {"error": {"message": "unknown model"}}), config=fast_config()
        )

        with pytest.raises(LLMRequestRejectedError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_REQUEST_REJECTED

    async def test_a_rejected_request_is_not_retried(self) -> None:
        seen: list[httpx2.Request] = []
        provider = stubbed_provider(
            json_handler(400, {"error": {"message": "unknown model"}}, seen=seen),
            config=fast_config(max_retries=3),
        )

        with pytest.raises(LLMRequestRejectedError):
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert len(seen) == 1


class TestAnUnusableAnswerIsNeverCoerced:
    """`PROJECT.md` §29: never silently invent evidence — not even by omission."""

    async def test_a_truncated_response_raises_and_names_the_cause(self) -> None:
        provider = stubbed_provider(
            json_handler(200, truncated_response_body()), config=fast_config()
        )

        with pytest.raises(LLMResponseError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_INVALID_RESPONSE
        assert "cut short" in str(caught.value)
        assert "max_output_tokens" in str(caught.value)

    async def test_a_refusal_raises_and_quotes_it(self) -> None:
        provider = stubbed_provider(
            json_handler(200, refusal_response_body()), config=fast_config()
        )

        with pytest.raises(LLMResponseError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert "refused" in str(caught.value)
        assert "I will not answer that." in str(caught.value)

    async def test_an_answer_missing_a_field_raises_rather_than_half_filling_the_model(
        self,
    ) -> None:
        provider = stubbed_provider(_answering({"verdict": "polling"}), config=fast_config())

        with pytest.raises(LLMResponseError) as caught:
            await provider.complete_structured(prompt="classify", response_model=Verdict)

        assert caught.value.kind is FailureKind.LLM_INVALID_RESPONSE
        assert "Verdict" in str(caught.value)


class TestEveryFailureNamesItsKind:
    def test_all_provider_errors_carry_a_failure_kind(self) -> None:
        """The pipeline reads `.kind` off whatever it catches — none may lack one.

        ``FailureKind.UNEXPECTED_ERROR`` (plan §10 Phase 13) is deliberately
        excluded: it names a non-LLM failure the worker's own error contract
        catches, not something any ``LLMProviderError`` subclass raises.
        """
        errors: list[LLMProviderError] = [
            LLMCredentialError("no key"),
            LLMUnavailableError("timeout"),
            LLMRequestRejectedError("bad model"),
            LLMResponseError("refused"),
        ]

        assert {error.kind for error in errors} == set(FailureKind) - {FailureKind.UNEXPECTED_ERROR}


# Plan §2.15 — every call records what it used, so "a cache hit saves money"
# is a reading off two runs rather than a claim about them.


async def test_a_call_records_the_tokens_it_used() -> None:
    ledger = TokenLedger()
    provider = stubbed_provider(
        json_handler(
            200,
            response_body(
                {"verdict": "yes", "confidence": 0.9},
                usage=usage(input_tokens=1840, output_tokens=260),
            ),
        ),
        ledger=ledger,
    )

    await provider.complete_structured(prompt="anything", response_model=Verdict)

    assert ledger.totals() == {
        "llm_calls": 1,
        "llm_prompt_tokens": 1840,
        "llm_completion_tokens": 260,
        "llm_total_tokens": 2100,
        "llm_calls_without_usage": 0,
    }


async def test_calls_accumulate_across_a_run() -> None:
    ledger = TokenLedger()
    provider = stubbed_provider(
        json_handler(
            200,
            response_body(
                {"verdict": "yes", "confidence": 0.9},
                usage=usage(input_tokens=100, output_tokens=20),
            ),
        ),
        ledger=ledger,
    )

    for _ in range(3):
        await provider.complete_structured(prompt="anything", response_model=Verdict)

    assert ledger.calls == 3
    assert ledger.totals()["llm_total_tokens"] == 360


async def test_a_response_without_a_usage_block_is_unknown_not_free() -> None:
    """Plan §0.1: an unmeasured call must not read as a call that cost nothing."""
    ledger = TokenLedger()
    provider = stubbed_provider(
        json_handler(200, response_body({"verdict": "yes", "confidence": 0.9})),
        ledger=ledger,
    )

    await provider.complete_structured(prompt="anything", response_model=Verdict)

    assert ledger.totals()["llm_calls"] == 1
    assert ledger.totals()["llm_calls_without_usage"] == 1
    assert ledger.totals()["llm_total_tokens"] == 0


async def test_an_answer_that_cannot_be_used_is_still_an_answer_that_was_billed() -> None:
    """A refusal costs exactly what a useful reply costs, and is recorded as such.

    Counting only the successful calls would understate precisely the runs
    worth investigating — the ones that failed expensively.
    """
    ledger = TokenLedger()
    provider = stubbed_provider(
        json_handler(
            200,
            refusal_response_body() | {"usage": usage(input_tokens=900, output_tokens=15)},
        ),
        ledger=ledger,
    )

    with pytest.raises(LLMResponseError):
        await provider.complete_structured(prompt="anything", response_model=Verdict)

    assert ledger.totals()["llm_calls"] == 1
    assert ledger.totals()["llm_total_tokens"] == 915


async def test_a_provider_without_a_ledger_still_answers() -> None:
    """Recording is optional — every existing caller builds one without a ledger."""
    provider = stubbed_provider(
        json_handler(200, response_body({"verdict": "yes", "confidence": 0.9}))
    )

    assert (
        await provider.complete_structured(prompt="anything", response_model=Verdict)
    ).verdict == "yes"
