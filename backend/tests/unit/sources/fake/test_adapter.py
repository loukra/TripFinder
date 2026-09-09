from tripfinder.domain.ports import SourceAdapter, SourceSearchQuery
from tripfinder.sources.fake.adapter import FakeSourceAdapter
from tripfinder.sources.fake.fixtures import fixture_comments, fixture_documents


def _adapter() -> FakeSourceAdapter:
    return FakeSourceAdapter(documents=fixture_documents(), comments=fixture_comments())


def test_satisfies_source_adapter_protocol() -> None:
    assert isinstance(_adapter(), SourceAdapter)


async def test_health_check_is_always_true_and_makes_no_calls() -> None:
    assert await _adapter().health_check() is True


async def test_search_returns_fixture_documents_up_to_limit() -> None:
    adapter = _adapter()

    results = await adapter.search(SourceSearchQuery(query="anything", limit=1))

    assert [document.id for document in results] == ["post1"]


async def test_search_ignores_query_text_and_returns_fixtures() -> None:
    adapter = _adapter()

    results = await adapter.search(SourceSearchQuery(query="irrelevant text"))

    assert {document.id for document in results} == {"post1", "post2"}


async def test_fetch_document_returns_matching_document() -> None:
    adapter = _adapter()

    document = await adapter.fetch_document("post2")

    assert document.title == "Hidden gem national parks"


async def test_fetch_document_raises_for_unknown_id() -> None:
    adapter = _adapter()

    try:
        await adapter.fetch_document("does-not-exist")
    except LookupError:
        return
    raise AssertionError("expected LookupError")


async def test_fetch_comments_returns_fixture_comments_for_document() -> None:
    adapter = _adapter()
    document = await adapter.fetch_document("post1")

    comments = await adapter.fetch_comments(document)

    assert [comment.id for comment in comments] == ["c1", "c2", "c3"]


async def test_fetch_comments_returns_empty_for_document_with_none_registered() -> None:
    adapter = FakeSourceAdapter(documents=fixture_documents())
    document = await adapter.fetch_document("post1")

    comments = await adapter.fetch_comments(document)

    assert comments == []
