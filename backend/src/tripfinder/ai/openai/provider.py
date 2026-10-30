"""OpenAI behind the ``LLMProvider`` port (plan §1, §13, §10 Phase 7.5).

Structured output goes through the Responses API's ``parse`` helper: it
sends the requested Pydantic model as a strict JSON schema and returns a
validated instance, which is the guarantee `PROJECT.md` demands of every AI
step in this system.

**Every failure here is loud.** Returning ``None``, an empty model, or a
half-filled one on error would hand the pipeline an empty analysis, and plan
§0.1's whole point is that such a run must never arrive looking like a
question nobody had an opinion about. Provider exceptions are therefore
mapped onto ``ai/errors.py`` and re-raised — the pipeline turns them into a
failed research with a named cause.
"""

from __future__ import annotations

from typing import Any

import openai
from openai import AsyncOpenAI, Omit, omit
from openai.types.responses import ParsedResponse
from openai.types.shared_params import Reasoning
from pydantic import BaseModel, SecretStr, ValidationError

from tripfinder.ai.errors import (
    LLMCredentialError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)
from tripfinder.ai.openai.config import OpenAIConfig
from tripfinder.domain.usage import CallUsage, TokenLedger

MISSING_KEY_MESSAGE = (
    "no OpenAI API key is configured, so no model call can be made "
    "(set OPENAI_API_KEY, or LLM_PROVIDER=fake)"
)


def _build_client(config: OpenAIConfig, api_key: SecretStr | None) -> AsyncOpenAI | None:
    """The SDK client, or ``None`` when there is no credential to build it with.

    A missing key must fail the *research*, with a reason the user can read
    (plan §10 Phase 7.5 acceptance) — not the process that constructed the
    provider. So construction stays silent and the first call is what raises.

    An empty key is a missing key. The SDK would otherwise fall back to
    reading ``OPENAI_API_KEY`` from the process environment, which would put
    a credential into a run that ``Settings`` never gave one.
    """
    key = api_key.get_secret_value().strip() if api_key is not None else ""
    if not key:
        return None
    return AsyncOpenAI(
        api_key=key,
        base_url=config.base_url,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )


def _usage_of(response: ParsedResponse[Any]) -> CallUsage | None:
    """What the Responses API said this call used, or ``None`` if it said nothing.

    ``None`` is not zero and must never be recorded as zero (plan §0.1 in
    its cheapest form): a response without a usage block is a call whose
    cost is *unknown*, and :class:`TokenLedger` counts those separately so a
    total can never quietly describe fewer calls than were made.
    """
    usage = response.usage
    if usage is None:
        return None
    return CallUsage(prompt_tokens=usage.input_tokens, completion_tokens=usage.output_tokens)


def _unusable_output_detail(response: ParsedResponse[Any]) -> str:
    """Why a 200 response still carried no answer."""
    if response.status == "incomplete":
        details = response.incomplete_details
        reason = details.reason if details is not None else None
        return f"the response was cut short ({reason or 'no reason given'})"
    for item in response.output:
        if item.type != "message":
            continue
        for part in item.content:
            if part.type == "refusal":
                return f"the model refused the request: {part.refusal}"
    return "the model returned no parsed output"


class OpenAIProvider:
    """Plan §1's locked provider, satisfying :class:`LLMProvider`.

    Retries, timeouts, the token cap and the reasoning effort are the SDK's,
    driven by :class:`OpenAIConfig` — the same division ``ArcticShiftClient``
    uses, where policy is configuration and this class only maps failures.
    Plan §2.10 asked that the first phase to call the provider set the effort
    deliberately rather than inherit whatever the model defaults to; §2.12
    measured what it is worth and 14.6b sets it.
    """

    def __init__(
        self,
        config: OpenAIConfig | None = None,
        *,
        api_key: SecretStr | None = None,
        client: AsyncOpenAI | None = None,
        ledger: TokenLedger | None = None,
    ) -> None:
        self._config = config or OpenAIConfig()
        self._client = client if client is not None else _build_client(self._config, api_key)
        self._ledger = ledger

    def _reasoning(self) -> Reasoning | Omit:
        """The configured effort, or the SDK's "say nothing" sentinel.

        Omitting the parameter and sending ``effort=None`` are different
        requests — the first leaves the model on its own default, the second
        asks for no reasoning at all — so a missing config value must not
        turn into a value (plan §2.10).
        """
        effort = self._config.reasoning_effort
        if effort is None:
            return omit
        return Reasoning(effort=effort.value)

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        if self._client is None:
            raise LLMCredentialError(MISSING_KEY_MESSAGE)

        try:
            response = await self._client.responses.parse(
                model=self._config.model,
                input=prompt,
                text_format=response_model,
                max_output_tokens=self._config.max_output_tokens,
                reasoning=self._reasoning(),
            )
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise LLMCredentialError(f"OpenAI rejected the API key: {exc}") from exc
        except openai.RateLimitError as exc:
            raise LLMUnavailableError(f"OpenAI rate-limited the request: {exc}") from exc
        except openai.APITimeoutError as exc:
            raise LLMUnavailableError(f"OpenAI timed out: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise LLMUnavailableError(f"OpenAI was unreachable: {exc}") from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMUnavailableError(f"OpenAI returned HTTP {exc.status_code}") from exc
            raise LLMRequestRejectedError(
                f"OpenAI rejected the request with HTTP {exc.status_code}: {exc}"
            ) from exc
        except (
            openai.LengthFinishReasonError,
            openai.ContentFilterFinishReasonError,
        ) as exc:
            raise LLMResponseError(f"OpenAI returned no usable answer: {exc}") from exc
        except ValidationError as exc:
            raise LLMResponseError(
                f"OpenAI's answer did not match {response_model.__name__}: {exc}"
            ) from exc

        # Recorded before the answer is judged usable: the call was made and
        # it was billed, whether or not what came back can be used (plan
        # §2.15). A cost that only appears on successful calls understates
        # exactly the runs worth investigating.
        if self._ledger is not None:
            self._ledger.record(_usage_of(response))

        parsed = response.output_parsed
        if parsed is None:
            raise LLMResponseError(
                f"OpenAI returned no usable {response_model.__name__}: "
                f"{_unusable_output_detail(response)}"
            )
        return parsed
