from collections.abc import Sequence

from pydantic import BaseModel

from tripfinder.domain.models import Comment, SourceDocument
from tripfinder.domain.ports import (
    LLMProvider,
    SourceAdapter,
    WebSearchHit,
    WebSearchProvider,
    WebSearchQuery,
)


class _FakeSourceAdapter:
    name = "fake"

    async def health_check(self) -> bool:
        return True

    async def fetch_documents(self, document_ids: Sequence[str]) -> Sequence[SourceDocument]:
        return []

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        return []


class _IncompleteSourceAdapter:
    name = "incomplete"

    async def health_check(self) -> bool:
        return True

    # missing fetch_documents / fetch_comments


class _FakeLLMProvider:
    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        return response_model.model_validate({})


class _NotAnLLMProvider:
    pass


class _FakeWebSearchProvider:
    name = "fake"

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        return []


def test_conforming_source_adapter_satisfies_protocol() -> None:
    assert isinstance(_FakeSourceAdapter(), SourceAdapter)


def test_incomplete_source_adapter_does_not_satisfy_protocol() -> None:
    assert not isinstance(_IncompleteSourceAdapter(), SourceAdapter)


def test_a_source_adapter_no_longer_needs_a_search_method() -> None:
    """Plan §2.11: the source is asked only for things it answers reliably.

    Stated as its own test because the absence of a method is exactly the
    kind of thing a future refactor reintroduces by accident.
    """
    assert not hasattr(SourceAdapter, "search")


def test_conforming_llm_provider_satisfies_protocol() -> None:
    assert isinstance(_FakeLLMProvider(), LLMProvider)


def test_unrelated_object_does_not_satisfy_llm_provider_protocol() -> None:
    assert not isinstance(_NotAnLLMProvider(), LLMProvider)


def test_conforming_web_search_provider_satisfies_protocol() -> None:
    assert isinstance(_FakeWebSearchProvider(), WebSearchProvider)


def test_unrelated_object_does_not_satisfy_web_search_provider_protocol() -> None:
    assert not isinstance(_NotAnLLMProvider(), WebSearchProvider)


def test_web_search_query_defaults_and_validation() -> None:
    query = WebSearchQuery(query="underrated nature USA")

    assert query.limit == 10

    restored = WebSearchQuery.model_validate_json(query.model_dump_json())

    assert restored == query


def test_a_web_search_hit_needs_only_a_url() -> None:
    """Title and snippet are aids to judgement, not evidence — an engine that
    returns neither still gives us a usable address (plan §2.11)."""
    hit = WebSearchHit(url="https://www.reddit.com/r/travel/comments/abc123/x/")

    assert hit.title == ""
    assert hit.snippet == ""
