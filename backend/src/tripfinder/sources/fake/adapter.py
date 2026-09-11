"""Fixture-backed SourceAdapter for tests and the fake pipeline (plan §3.1, §9).

Zero network calls. Documents and comments are supplied at construction time,
so callers control exactly what a research run discovers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from tripfinder.domain.models import Comment, SourceDocument


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

    async def fetch_documents(self, document_ids: Sequence[str]) -> Sequence[SourceDocument]:
        """Only the ids this fixture knows, in the order they were asked for.

        An unknown id is omitted rather than raising — the real adapter
        behaves the same way, because ``/api/posts/ids`` simply leaves an
        unknown id out of its response.
        """
        by_id = {document.id: document for document in self._documents}
        return [by_id[document_id] for document_id in document_ids if document_id in by_id]

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        return self._comments.get(document.id, [])
