"""Ports the domain depends on but does not implement (PROJECT.md §10, §13).

Only the protocols live here. Concrete adapters (Arctic Shift, OpenAI, fakes)
live in ``sources/`` and ``ai/`` and import *this* module — never the reverse.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from tripfinder.domain.models import Comment, SourceDocument


class SourceSearchQuery(BaseModel):
    """A single bounded search request issued to a SourceAdapter (PROJECT.md §10)."""

    query: str = Field(min_length=1)
    limit: int = Field(default=25, gt=0)


@runtime_checkable
class SourceAdapter(Protocol):
    """A source of discoverable documents and comments (PROJECT.md §10, §11).

    Implementations own retries, pagination, rate limits, and normalization
    to domain types. The research core never sees source-specific structures.
    """

    name: str

    async def health_check(self) -> bool: ...

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]: ...

    async def fetch_document(self, document_id: str) -> SourceDocument: ...

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]: ...


@runtime_checkable
class LLMProvider(Protocol):
    """A structured-output capable LLM, replaceable behind this port (PROJECT.md §13).

    Model IDs and other provider configuration live with the implementation,
    never in the domain layer.
    """

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T: ...
