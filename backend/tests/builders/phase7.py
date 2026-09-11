"""Builders for the triage/retrieval/pre-filter tests (plan §4.6 steps 4-6)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from pydantic import HttpUrl

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.domain.config import ResearchConfig
from tripfinder.domain.models import (
    Comment,
    EntityType,
    GeoScope,
    Research,
    ResearchPlan,
    ResearchStatus,
    SourceDocument,
)
from tripfinder.domain.ports import LLMProvider, SourceAdapter, WebSearchProvider
from tripfinder.pipeline.base import PipelineContext
from tripfinder.search.fake import FakeSearchProvider

NOW = datetime(2026, 9, 10, tzinfo=UTC)
"""A fixed "now" so document ages in these tests never drift."""

SUBSTANTIVE_BODY = "Honestly the Upper Peninsula is stunning and almost nobody goes there."


def make_plan(granularity: EntityType = EntityType.STATE) -> ResearchPlan:
    return ResearchPlan(
        normalized_query="underrated us states for nature",
        scope=GeoScope(type="country", value="United States"),
        entity_granularity=granularity,
        granularity_confidence=0.9,
        topic="nature",
        criteria=["underrated"],
    )


def make_document(
    document_id: str,
    *,
    title: str = "Most underrated state for nature?",
    comment_count: int = 50,
    age_years: float = 1.0,
    subreddit: str = "travel",
) -> SourceDocument:
    return SourceDocument(
        id=document_id,
        source="fake",
        title=title,
        url=HttpUrl(f"https://reddit.com/r/{subreddit}/{document_id}"),
        subreddit=subreddit,
        created_at=NOW - timedelta(days=age_years * 365.25),
        comment_count=comment_count,
    )


def make_comment(
    comment_id: str,
    *,
    document_id: str = "d1",
    user_id: str = "u1",
    body: str = SUBSTANTIVE_BODY,
    score: int | None = None,
) -> Comment:
    return Comment(
        id=comment_id,
        source_document_id=document_id,
        user_id=user_id,
        body=body,
        created_at=NOW - timedelta(days=30),
        permalink=HttpUrl(f"https://reddit.com/comments/{comment_id}"),
        score=score,
    )


def make_context(
    *,
    source: SourceAdapter | None = None,
    search: WebSearchProvider | None = None,
    llm: LLMProvider | None = None,
    config: ResearchConfig | None = None,
    status: ResearchStatus = ResearchStatus.RETRIEVING,
) -> PipelineContext:
    research = Research(
        original_query="Most underrated US states for nature",
        created_at=NOW,
        status=status,
        research_config=config or ResearchConfig(),
    )
    context = PipelineContext(
        research=research,
        source=source or RecordingSourceAdapter(),
        search=search or FakeSearchProvider(hits=[]),
        llm=llm or FakeLLMProvider(),
    )
    context.data["plan"] = make_plan()
    return context


class RecordingSourceAdapter:
    """A fake adapter that records which documents had their comments fetched."""

    name = "recording"

    def __init__(
        self,
        comments: Mapping[str, Sequence[Comment]] | None = None,
        *,
        documents: Sequence[SourceDocument] = (),
        failing: Mapping[str, Exception] | None = None,
    ) -> None:
        self._comments = dict(comments or {})
        self._documents = {document.id: document for document in documents}
        self._failing = dict(failing or {})
        self.fetched_document_ids: list[str] = []
        self.hydrated_batches: list[list[str]] = []

    async def health_check(self) -> bool:
        return True

    async def fetch_documents(self, document_ids: Sequence[str]) -> Sequence[SourceDocument]:
        self.hydrated_batches.append(list(document_ids))
        return [
            self._documents[document_id]
            for document_id in document_ids
            if document_id in self._documents
        ]

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        self.fetched_document_ids.append(document.id)
        if document.id in self._failing:
            raise self._failing[document.id]
        return self._comments.get(document.id, [])
