"""Content Retrieval (plan §4.6 step 5, §4.5 budget priority, §8.1 accounting)."""

from __future__ import annotations

from collections.abc import Sequence

from builders.phase7 import RecordingSourceAdapter, make_comment, make_context, make_document
from tripfinder.analysis.aliases import StaticAliasTable
from tripfinder.domain.config import ResearchBudget, ResearchConfig
from tripfinder.domain.models import (
    EntityType,
    ResearchFlag,
    ResearchStatus,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.health import get_recorder
from tripfinder.pipeline.steps.retrieval import ContentRetrievalStep
from tripfinder.pipeline.steps.triage import DocumentTriageStep


class Timeout(Exception):
    kind = "timeout"


def _triaged(
    context: PipelineContext,
    *,
    polling: Sequence[str] = (),
    topical: Sequence[str] = (),
) -> None:
    context.data["polling_documents"] = [make_document(document_id) for document_id in polling]
    context.data["topical_documents"] = [make_document(document_id) for document_id in topical]


async def test_fetches_comments_for_surviving_documents_only() -> None:
    """Triage runs before retrieval: an excluded document costs no fetch (plan §4.7)."""
    adapter = RecordingSourceAdapter(
        {"keep": [make_comment("c1", document_id="keep")], "dropped": []}
    )
    context = make_context(source=adapter)
    _triaged(context, polling=["keep"])

    await ContentRetrievalStep().run(context)

    assert adapter.fetched_document_ids == ["keep"]


async def test_an_excluded_document_has_no_comment_tree_fetched_end_to_end() -> None:
    """The same guarantee, driven through triage rather than asserted on its output."""
    adapter = RecordingSourceAdapter({"poll": [make_comment("c1", document_id="poll")]})
    context = make_context(source=adapter)
    context.data["documents"] = [
        make_document("poll", title="Most underrated state?"),
        make_document("tiny", comment_count=1),
    ]

    await DocumentTriageStep(StaticAliasTable({EntityType.STATE: ["Alaska"]})).run(context)
    await ContentRetrievalStep().run(context)

    assert "tiny" not in adapter.fetched_document_ids


async def test_polling_documents_are_retrieved_before_topical_ones() -> None:
    """Topical threads cannot change the ranking, so they spend leftover budget only."""
    adapter = RecordingSourceAdapter()
    context = make_context(source=adapter)
    _triaged(context, polling=["p1", "p2"], topical=["t1"])

    await ContentRetrievalStep().run(context)

    assert adapter.fetched_document_ids == ["p1", "p2", "t1"]


async def test_comments_are_split_by_the_context_type_of_their_document() -> None:
    adapter = RecordingSourceAdapter(
        {
            "p1": [make_comment("c1", document_id="p1", user_id="u1")],
            "t1": [make_comment("c2", document_id="t1", user_id="u2")],
        }
    )
    context = make_context(source=adapter)
    _triaged(context, polling=["p1"], topical=["t1"])

    await ContentRetrievalStep().run(context)

    assert [comment.id for comment in context.data["polling_comments"]] == ["c1"]
    assert [comment.id for comment in context.data["topical_comments"]] == ["c2"]
    assert [comment.id for comment in context.data["comments"]] == ["c1", "c2"]


async def test_a_comment_seen_twice_is_kept_once_and_recorded() -> None:
    duplicate = make_comment("shared", document_id="p1")
    adapter = RecordingSourceAdapter({"p1": [duplicate], "p2": [duplicate]})
    context = make_context(source=adapter)
    _triaged(context, polling=["p1", "p2"])

    await ContentRetrievalStep().run(context)

    assert [comment.id for comment in context.data["comments"]] == ["shared"]
    (suppression,) = [
        entry
        for entry in context.research.diagnostics.suppressions
        if entry.reason is SuppressionReason.DUPLICATE_COMMENT
    ]
    assert suppression.count == 1


async def test_the_comment_budget_caps_the_corpus_and_says_so() -> None:
    adapter = RecordingSourceAdapter(
        {"p1": [make_comment(f"c{index}", document_id="p1") for index in range(5)]}
    )
    config = ResearchConfig(budget=ResearchBudget(max_comments=3))
    context = make_context(source=adapter, config=config)
    _triaged(context, polling=["p1", "p2"])

    await ContentRetrievalStep().run(context)

    assert len(context.data["comments"]) == 3
    (suppression,) = [
        entry
        for entry in context.research.diagnostics.suppressions
        if entry.reason is SuppressionReason.BUDGET_MAX_COMMENTS
        and "comments dropped" in (entry.detail or "")
    ]
    assert suppression.count == 2
    assert ResearchFlag.BUDGET_LIMIT_REACHED in context.research.diagnostics.flags


async def test_an_exhausted_budget_stops_visiting_further_documents() -> None:
    adapter = RecordingSourceAdapter(
        {"p1": [make_comment(f"c{index}", document_id="p1") for index in range(3)]}
    )
    config = ResearchConfig(budget=ResearchBudget(max_comments=3))
    context = make_context(source=adapter, config=config)
    _triaged(context, polling=["p1", "p2"], topical=["t1"])

    await ContentRetrievalStep().run(context)

    assert adapter.fetched_document_ids == ["p1"]
    (suppression,) = [
        entry
        for entry in context.research.diagnostics.suppressions
        if "never fetched" in (entry.detail or "")
    ]
    assert suppression.count == 2


async def test_a_successful_fetch_is_recorded_in_source_health() -> None:
    adapter = RecordingSourceAdapter({"p1": [make_comment("c1", document_id="p1")]})
    context = make_context(source=adapter)
    _triaged(context, polling=["p1"])

    await ContentRetrievalStep().run(context)

    (health,) = get_recorder(context).snapshot()
    assert (health.adapter, health.calls_succeeded, health.calls_failed) == ("recording", 1, 0)


async def test_one_failing_document_does_not_end_the_pass_and_is_accounted_for() -> None:
    adapter = RecordingSourceAdapter(
        {"p2": [make_comment("c1", document_id="p2")]}, failing={"p1": Timeout("slow")}
    )
    context = make_context(source=adapter)
    _triaged(context, polling=["p1", "p2"])

    await ContentRetrievalStep().run(context)

    assert adapter.fetched_document_ids == ["p1", "p2"]
    assert [comment.id for comment in context.data["comments"]] == ["c1"]

    (health,) = get_recorder(context).snapshot()
    assert health.calls_attempted == 2
    assert health.failure_kinds == {"timeout": 1}

    assert any(
        entry.reason is SuppressionReason.RETRIEVAL_SOURCE_FAILURE
        for entry in context.research.diagnostics.suppressions
    )


async def test_an_unclassified_failure_still_counts_against_health() -> None:
    adapter = RecordingSourceAdapter(failing={"p1": RuntimeError("boom")})
    context = make_context(source=adapter)
    _triaged(context, polling=["p1"])

    await ContentRetrievalStep().run(context)

    (health,) = get_recorder(context).snapshot()
    assert health.failure_kinds == {"unknown": 1}


async def test_posts_retrieved_counts_only_successful_fetches() -> None:
    adapter = RecordingSourceAdapter(
        {"p2": [make_comment("c1", document_id="p2")]}, failing={"p1": Timeout("slow")}
    )
    context = make_context(source=adapter)
    _triaged(context, polling=["p1", "p2"])

    await ContentRetrievalStep().run(context)

    assert context.data["posts_retrieved"] == 1
    assert context.research.statistics["documents_retrieved"] == 1


async def test_statistics_record_the_split_corpus() -> None:
    adapter = RecordingSourceAdapter(
        {
            "p1": [make_comment("c1", document_id="p1"), make_comment("c2", document_id="p1")],
            "t1": [make_comment("c3", document_id="t1")],
        }
    )
    context = make_context(source=adapter)
    _triaged(context, polling=["p1"], topical=["t1"])

    await ContentRetrievalStep().run(context)

    assert context.research.statistics["comments_retrieved"] == 3
    assert context.research.statistics["polling_comments_retrieved"] == 2
    assert context.research.statistics["topical_comments_retrieved"] == 1


async def test_the_step_advances_the_research_to_analyzing() -> None:
    context = make_context(status=ResearchStatus.RETRIEVING)
    _triaged(context)

    await ContentRetrievalStep().run(context)

    assert context.research.status is ResearchStatus.ANALYZING


# Plan §2.14.2 — breadth before depth. §2.12.3's finding 1 measured the
# absence of this: the budget was spent document by document, so 13 of 25
# threads supplied everything and doubling the analysis budget afterwards
# *lowered* the yield, because a deeper sample of the same threads is
# largely the same people again.


def _fat(document_id: str, count: int) -> list:
    return [
        make_comment(
            f"{document_id}-c{index}",
            document_id=document_id,
            user_id=f"{document_id}-u{index}",
            score=index,
        )
        for index in range(count)
    ]


async def test_one_thread_cannot_fill_the_corpus_by_itself() -> None:
    adapter = RecordingSourceAdapter({"big": _fat("big", 500), "small": _fat("small", 10)})
    context = make_context(
        config=ResearchConfig(
            budget=ResearchBudget(max_comments=200, max_comments_per_document=50)
        ),
        source=adapter,
    )
    _triaged(context, polling=["big", "small"])

    await ContentRetrievalStep().run(context)

    retrieved = context.data["polling_comments"]
    assert len(retrieved) == 60
    # Both threads are represented, which is the whole point: the small one
    # would have been reached in neither the old order nor a raised budget.
    assert {comment.source_document_id for comment in retrieved} == {"big", "small"}


async def test_the_cap_keeps_each_documents_best_scoring_comments() -> None:
    adapter = RecordingSourceAdapter({"big": _fat("big", 20)})
    context = make_context(
        config=ResearchConfig(
            budget=ResearchBudget(max_comments=100, max_comments_per_document=3)
        ),
        source=adapter,
    )
    _triaged(context, polling=["big"])

    await ContentRetrievalStep().run(context)

    assert {comment.id for comment in context.data["polling_comments"]} == {
        "big-c19",
        "big-c18",
        "big-c17",
    }


async def test_what_the_cap_dropped_is_recorded_rather_than_silently_lost() -> None:
    adapter = RecordingSourceAdapter({"big": _fat("big", 100)})
    context = make_context(
        config=ResearchConfig(
            budget=ResearchBudget(max_comments=1000, max_comments_per_document=40)
        ),
        source=adapter,
    )
    _triaged(context, polling=["big"])

    await ContentRetrievalStep().run(context)

    dropped = [
        suppression
        for suppression in context.research.diagnostics.suppressions
        if suppression.reason is SuppressionReason.BUDGET_MAX_COMMENTS
        and "each document" in (suppression.detail or "")
    ]
    assert sum(suppression.count for suppression in dropped) == 60


async def test_freed_budget_reaches_the_threads_that_were_never_opened() -> None:
    """The measured failure, as a test: three fat threads consumed a 600
    comment budget in document order and the fourth was never fetched."""
    adapter = RecordingSourceAdapter(
        {name: _fat(name, 300) for name in ("t1", "t2", "t3", "t4")}
    )
    context = make_context(
        config=ResearchConfig(
            budget=ResearchBudget(max_comments=600, max_comments_per_document=150)
        ),
        source=adapter,
    )
    _triaged(context, polling=["t1", "t2", "t3", "t4"])

    await ContentRetrievalStep().run(context)

    assert context.research.statistics["documents_retrieved"] == 4
    assert {
        comment.source_document_id for comment in context.data["polling_comments"]
    } == {"t1", "t2", "t3", "t4"}
