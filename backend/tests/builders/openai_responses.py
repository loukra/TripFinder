"""Responses API bodies for the OpenAI provider tests (plan §9).

A builder package rather than a conftest, because these are values several
test modules construct — the test tree has no ``__init__.py``, so a helper
that is not a fixture has to live somewhere importable.
"""

from __future__ import annotations

import json
from typing import Any


def response_body(
    payload: dict[str, Any],
    *,
    status: str = "completed",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A Responses API body carrying ``payload`` as the model's structured answer.

    ``usage`` is omitted by default, which is what a body that reports no
    token counts looks like — the case plan §2.15 requires to stay
    *unknown* rather than collapse to zero.
    """
    body: dict[str, Any] = {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5-mini",
        "status": status,
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": json.dumps(payload), "annotations": []}
                ],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def usage(*, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    """The usage block the Responses API returns beside an answer."""
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
    }


def truncated_response_body(reason: str = "max_output_tokens") -> dict[str, Any]:
    """A response the model ran out of tokens partway through — no answer at all."""
    body = response_body({}, status="incomplete")
    body["output"] = []
    body["incomplete_details"] = {"reason": reason}
    return body


def refusal_response_body(refusal: str = "I will not answer that.") -> dict[str, Any]:
    """A response whose only content is the model declining."""
    body = response_body({})
    body["output"] = [
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "refusal", "refusal": refusal}],
        }
    ]
    return body
