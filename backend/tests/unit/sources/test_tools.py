from collections.abc import Sequence

from tripfinder.domain.models import Comment, SourceDocument
from tripfinder.domain.ports import SourceSearchQuery
from tripfinder.sources.failures import UNKNOWN_FAILURE_KIND
from tripfinder.sources.fake.fixtures import fixture_documents
from tripfinder.sources.tools import SourceSearchTool


class _RecordingAdapter:
    """Records every search call it receives, for asserting what the tool sends on."""

    name = "recording"

    def __init__(self) -> None:
        self.calls: list[SourceSearchQuery] = []

    async def health_check(self) -> bool:
        return True

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        self.calls.append(query)
        return fixture_documents()

    async def fetch_document(self, document_id: str) -> SourceDocument:
        raise NotImplementedError

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        raise NotImplementedError


class _FailingAdapter:
    """Always raises, to prove the tool never lets an adapter failure escape."""

    name = "failing"

    async def health_check(self) -> bool:
        return True

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        raise TimeoutError("arctic shift did not respond")

    async def fetch_document(self, document_id: str) -> SourceDocument:
        raise NotImplementedError

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        raise NotImplementedError


async def test_search_returns_the_adapters_documents() -> None:
    tool = SourceSearchTool(_RecordingAdapter(), limit_per_query=25)

    result = await tool.search("underrated states nature")

    assert result.ok is True
    assert result.error is None
    assert [document.id for document in result.documents] == ["post1", "post2"]


async def test_search_passes_only_query_text_and_limit_to_the_adapter() -> None:
    adapter = _RecordingAdapter()
    tool = SourceSearchTool(adapter, limit_per_query=7)

    await tool.search("hidden gem parks")

    assert len(adapter.calls) == 1
    assert adapter.calls[0] == SourceSearchQuery(query="hidden gem parks", limit=7)


async def test_adapter_failure_becomes_a_structured_result_not_an_exception() -> None:
    tool = SourceSearchTool(_FailingAdapter(), limit_per_query=25)

    result = await tool.search("underrated states nature")

    assert result.ok is False
    assert result.documents == []
    assert "arctic shift did not respond" in (result.error or "")


async def test_a_failed_search_reports_its_failure_kind() -> None:
    """So health accounting can label the failure without inspecting the exception."""

    class _KindedFailure(Exception):
        kind = "rate_limited"

    class _Failing:
        name = "failing"

        async def health_check(self) -> bool:
            return True

        async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
            raise _KindedFailure("429")

        async def fetch_document(self, document_id: str) -> SourceDocument:
            raise LookupError(document_id)

        async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
            return []

    result = await SourceSearchTool(_Failing(), limit_per_query=5).search("anything")

    assert result.ok is False
    assert result.failure_kind == "rate_limited"


async def test_an_unclassified_failure_reports_an_unknown_kind() -> None:
    class _Failing:
        name = "failing"

        async def health_check(self) -> bool:
            return True

        async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
            raise RuntimeError("boom")

        async def fetch_document(self, document_id: str) -> SourceDocument:
            raise LookupError(document_id)

        async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
            return []

    result = await SourceSearchTool(_Failing(), limit_per_query=5).search("anything")

    assert result.failure_kind == UNKNOWN_FAILURE_KIND


async def test_a_successful_search_reports_no_failure_kind() -> None:
    class _Working:
        name = "working"

        async def health_check(self) -> bool:
            return True

        async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
            return []

        async def fetch_document(self, document_id: str) -> SourceDocument:
            raise LookupError(document_id)

        async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
            return []

    result = await SourceSearchTool(_Working(), limit_per_query=5).search("anything")

    assert result.ok is True
    assert result.failure_kind is None
