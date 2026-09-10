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
from openai import AsyncOpenAI
from openai.types.responses import ParsedResponse
from pydantic import BaseModel, SecretStr, ValidationError

from tripfinder.ai.errors import (
    LLMCredentialError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)
from tripfinder.ai.openai.config import OpenAIConfig

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

    Retries, timeouts and the token cap are the SDK's, driven by
    :class:`OpenAIConfig` — the same division ``ArcticShiftClient`` uses,
    where policy is configuration and this class only maps failures.
    """

    def __init__(
        self,
        config: OpenAIConfig | None = None,
        *,
        api_key: SecretStr | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._config = config or OpenAIConfig()
        self._client = client if client is not None else _build_client(self._config, api_key)

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

        parsed = response.output_parsed
        if parsed is None:
            raise LLMResponseError(
                f"OpenAI returned no usable {response_model.__name__}: "
                f"{_unusable_output_detail(response)}"
            )
        return parsed
