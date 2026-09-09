from collections.abc import Sequence

from pydantic import BaseModel

from tripfinder.domain.models import Comment, SourceDocument
from tripfinder.domain.ports import LLMProvider, SourceAdapter, SourceSearchQuery


class _FakeSourceAdapter:
    name = "fake"

    async def health_check(self) -> bool:
        return True

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        return []

    async def fetch_document(self, document_id: str) -> SourceDocument:
        raise NotImplementedError

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        return []


class _IncompleteSourceAdapter:
    name = "incomplete"

    async def health_check(self) -> bool:
        return True

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        return []

    # missing fetch_document / fetch_comments


class _FakeLLMProvider:
    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        return response_model.model_validate({})


class _NotAnLLMProvider:
    pass


def test_conforming_source_adapter_satisfies_protocol() -> None:
    assert isinstance(_FakeSourceAdapter(), SourceAdapter)


def test_incomplete_source_adapter_does_not_satisfy_protocol() -> None:
    assert not isinstance(_IncompleteSourceAdapter(), SourceAdapter)


def test_conforming_llm_provider_satisfies_protocol() -> None:
    assert isinstance(_FakeLLMProvider(), LLMProvider)


def test_unrelated_object_does_not_satisfy_llm_provider_protocol() -> None:
    assert not isinstance(_NotAnLLMProvider(), LLMProvider)


def test_source_search_query_defaults_and_validation() -> None:
    query = SourceSearchQuery(query="underrated nature USA")

    assert query.limit == 25

    restored = SourceSearchQuery.model_validate_json(query.model_dump_json())

    assert restored == query
