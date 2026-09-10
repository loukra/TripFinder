"""Responses API bodies for the OpenAI provider tests (plan §9).

A builder package rather than a conftest, because these are values several
test modules construct — the test tree has no ``__init__.py``, so a helper
that is not a fixture has to live somewhere importable.
"""

from __future__ import annotations

import json
from typing import Any


def response_body(payload: dict[str, Any], *, status: str = "completed") -> dict[str, Any]:
    """A Responses API body carrying ``payload`` as the model's structured answer."""
    return {
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
