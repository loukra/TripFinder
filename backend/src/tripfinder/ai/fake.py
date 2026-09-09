"""Deterministic, offline LLMProvider for tests and the fake pipeline (plan §9).

Phase 2 needs only a canned-response lookup keyed by response model type. The
plan's fuller description (prompt-hash keying, simulated malformed output,
refusals, timeouts) is testing infrastructure later phases will need once
they have real prompts and failure modes to simulate — see Known limitations
in the phase report.
"""

from __future__ import annotations

from pydantic import BaseModel


class FakeLLMProvider:
    """Returns the canned response registered for a given response model type.

    A request for an unregistered type raises rather than guessing, so a
    missing fixture fails loudly instead of silently returning nonsense.
    """

    def __init__(self, responses: dict[type[BaseModel], BaseModel] | None = None) -> None:
        self._responses = dict(responses or {})

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        try:
            response = self._responses[response_model]
        except KeyError:
            raise LookupError(
                f"FakeLLMProvider has no canned response registered for "
                f"{response_model.__name__}"
            ) from None

        if not isinstance(response, response_model):
            raise TypeError(
                f"FakeLLMProvider response registered for {response_model.__name__} "
                f"is a {type(response).__name__}, not a {response_model.__name__}"
            )

        return response
