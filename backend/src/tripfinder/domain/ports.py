"""Ports the domain depends on but does not implement (PROJECT.md §10, §13).

Only the protocols live here. Concrete adapters (Arctic Shift, OpenAI, fakes)
live in ``sources/`` and ``ai/`` and import *this* module — never the reverse.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from tripfinder.domain.models import Comment, Research, SourceDocument


class WebSearchQuery(BaseModel):
    """A single bounded web search, issued to a WebSearchProvider (plan §2.11)."""

    query: str = Field(min_length=1)
    limit: int = Field(default=10, gt=0)


class WebSearchHit(BaseModel):
    """One result from a web search provider — an address, never evidence.

    Plan §2.11 is explicit that web search supplies thread *addresses* only.
    ``title`` and ``snippet`` exist to let discovery judge whether an address
    is worth hydrating; nothing here ever reaches the analysed corpus, which
    is retrieved from the source adapter in full.
    """

    url: str = Field(min_length=1)
    title: str = ""
    snippet: str = ""


@runtime_checkable
class WebSearchProvider(Protocol):
    """A web search engine, replaceable behind this port (plan §2.11).

    Implementations own their credentials, retries, and result parsing. The
    research core sees only queries in and hits out — it does not know which
    engine answered, and no API key crosses this boundary.
    """

    name: str

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]: ...


@runtime_checkable
class SourceAdapter(Protocol):
    """A source of retrievable documents and comments (PROJECT.md §10, §11).

    Implementations own retries, pagination, rate limits, and normalization
    to domain types. The research core never sees source-specific structures.

    There is deliberately no ``search`` here (plan §2.11): documents are
    found by address through a ``WebSearchProvider`` and fetched by id, so a
    source is asked only for things it can answer reliably.
    """

    name: str

    async def health_check(self) -> bool: ...

    async def fetch_documents(self, document_ids: Sequence[str]) -> Sequence[SourceDocument]: ...

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]: ...


@runtime_checkable
class AnswerArchive(Protocol):
    """Answers this product has already produced, looked up by plan (plan §2.15).

    A port rather than a repository call, for the reason every other port
    here exists: the pipeline has no database and must not grow one. The
    worker hands it a reader backed by the ``research`` table; tests hand it
    a list. Neither is visible to the step that asks.

    The *policy* — what may be reused, and how old is too old — is not in
    here. This answers one narrow question: which stored run, if any, has
    this fingerprint and is recent enough. Whether that run finished
    properly, and whether it was itself reusing, is decided by
    ``AnswerReuseStep`` against the run it gets back, where the reasoning is
    visible and testable without a database.
    """

    async def find_by_fingerprint(
        self, *, fingerprint: str, not_before: datetime
    ) -> Research | None:
        """The most recent run with this fingerprint created at or after ``not_before``."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """A structured-output capable LLM, replaceable behind this port (PROJECT.md §13).

    Model IDs and other provider configuration live with the implementation,
    never in the domain layer.
    """

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T: ...
