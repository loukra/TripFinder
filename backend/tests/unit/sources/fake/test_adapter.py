from tripfinder.domain.ports import SourceAdapter
from tripfinder.sources.fake.adapter import FakeSourceAdapter
from tripfinder.sources.fake.fixtures import fixture_comments, fixture_documents


def _adapter() -> FakeSourceAdapter:
    return FakeSourceAdapter(documents=fixture_documents(), comments=fixture_comments())


def test_satisfies_source_adapter_protocol() -> None:
    assert isinstance(_adapter(), SourceAdapter)


async def test_health_check_is_always_true_and_makes_no_calls() -> None:
    assert await _adapter().health_check() is True


async def test_fetch_documents_returns_the_requested_ids_in_order() -> None:
    adapter = _adapter()

    documents = await adapter.fetch_documents(["post2", "post1"])

    assert [document.id for document in documents] == ["post2", "post1"]


async def test_fetch_documents_omits_ids_the_fixture_does_not_know() -> None:
    """Matching the real adapter: ``/api/posts/ids`` leaves an unknown id out."""
    adapter = _adapter()

    documents = await adapter.fetch_documents(["post1", "does-not-exist"])

    assert [document.id for document in documents] == ["post1"]


async def test_fetch_documents_returns_nothing_for_an_empty_request() -> None:
    assert await _adapter().fetch_documents([]) == []


async def test_fetch_comments_returns_fixture_comments_for_document() -> None:
    adapter = _adapter()
    (document,) = await adapter.fetch_documents(["post1"])

    comments = await adapter.fetch_comments(document)

    assert [comment.id for comment in comments] == ["c1", "c2", "c3"]


async def test_fetch_comments_returns_empty_for_document_with_none_registered() -> None:
    adapter = FakeSourceAdapter(documents=fixture_documents())
    (document,) = await adapter.fetch_documents(["post1"])

    comments = await adapter.fetch_comments(document)

    assert comments == []
