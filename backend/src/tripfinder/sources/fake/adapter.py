"""Fixture-backed SourceAdapter for tests and the fake pipeline (plan §3.1, §9).

Zero network calls. Documents and comments are supplied at construction time,
so callers control exactly what a research run discovers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from tripfinder.domain.models import Comment, SourceDocument
from tripfinder.domain.ports import SourceSearchQuery


class FakeSourceAdapter:
    """Serves documents/comments from an in-memory fixture."""

    name = "fake"

    def __init__(
        self,
        *,
        documents: Sequence[SourceDocument] = (),
        comments: Mapping[str, Sequence[Comment]] | None = None,
    ) -> None:
        self._documents = list(documents)
        self._comments = dict(comments or {})

    async def health_check(self) -> bool:
        return True

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        return self._documents[: query.limit]

    async def fetch_document(self, document_id: str) -> SourceDocument:
        for document in self._documents:
            if document.id == document_id:
                return document
        raise LookupError(f"FakeSourceAdapter has no document {document_id!r}")

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        return self._comments.get(document.id, [])
