"""Deterministic, offline LLMProvider for tests and the fake pipeline (plan §9).

Phase 2 needed only a canned-response lookup keyed by response model type.
Phase 6's discovery agent loop calls the same response model repeatedly with
a different answer expected each turn, so a registration may also be a
sequence: one response drained per call, in order. The plan's fuller
description (prompt-hash keying, simulated malformed output, refusals,
timeouts) remains for whichever later phase first needs it.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from tripfinder.domain.usage import TokenLedger


class FakeLLMProvider:
    """Returns the canned response(s) registered for a given response model type.

    Register a single ``BaseModel`` to return the same response for every
    call. Register a ``Sequence`` to drain one response per call, in order —
    for a caller that makes several turns and expects a different answer
    each time. Either way, a request for an unregistered type, or a queue
    with nothing left, raises rather than guessing.
    """

    def __init__(
        self,
        responses: Mapping[type[BaseModel], BaseModel | Sequence[BaseModel]] | None = None,
        *,
        ledger: TokenLedger | None = None,
    ) -> None:
        self._ledger = ledger
        self._fixed: dict[type[BaseModel], BaseModel] = {}
        self._queues: dict[type[BaseModel], deque[BaseModel]] = {}
        for response_model, value in (responses or {}).items():
            if isinstance(value, BaseModel):
                self._fixed[response_model] = value
            else:
                self._queues[response_model] = deque(value)

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        # A canned answer costs no tokens, and reporting *zero* would be a
        # lie of a particular kind: it would make a run against this
        # provider look like a run that spent nothing, rather than one
        # nobody measured. ``record(None)`` counts the call and files its
        # cost as unknown (plan §2.15).
        if self._ledger is not None:
            self._ledger.record(None)

        if response_model in self._queues:
            queue = self._queues[response_model]
            if not queue:
                raise LookupError(
                    f"FakeLLMProvider's queued responses for "
                    f"{response_model.__name__} are exhausted"
                )
            response = queue.popleft()
        elif response_model in self._fixed:
            response = self._fixed[response_model]
        else:
            raise LookupError(
                f"FakeLLMProvider has no canned response registered for "
                f"{response_model.__name__}"
            )

        if not isinstance(response, response_model):
            raise TypeError(
                f"FakeLLMProvider response registered for {response_model.__name__} "
                f"is a {type(response).__name__}, not a {response_model.__name__}"
            )

        return response
