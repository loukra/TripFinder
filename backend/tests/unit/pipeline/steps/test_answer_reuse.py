"""Answering a question already answered (plan §2.15, §4.6 step 1.5).

Every test here runs against adapters that raise if touched, because that is
the claim the phase makes: a hit costs no discovery call, no retrieval and no
analysis. A step that reused an answer *and* went looking anyway would pass a
test that only checked the ranking.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel

from tripfinder.domain.config import ResearchConfig, ReuseConfig
from tripfinder.domain.models import (
    Comment,
    EntityType,
    FailureKind,
    GeoScope,
    Research,
    ResearchPlan,
    ResearchStatus,
    Result,
    ReusedAnswer,
    SourceDocument,
    SuppressionReason,
)
from tripfinder.domain.ports import WebSearchHit, WebSearchQuery
from tripfinder.domain.reuse import plan_fingerprint
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.answer_reuse import AnswerReuseStep

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


class _ForbiddenSource:
    name = "forbidden"

    async def health_check(self) -> bool:
        raise AssertionError("a reused answer must cost no source call")

    async def fetch_documents(self, document_ids: Sequence[str]) -> Sequence[SourceDocument]:
        raise AssertionError("a reused answer must cost no source call")

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        raise AssertionError("a reused answer must cost no source call")


class _ForbiddenSearch:
    name = "forbidden"

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        raise AssertionError("a reused answer must cost no search call")


class _ForbiddenLLM:
    async def complete_structured[T: BaseModel](self, *, prompt: str, response_model: type[T]) -> T:
        raise AssertionError("a reused answer must cost no model call")


class _Archive:
    """One stored run, plus a record of what it was asked for."""

    def __init__(self, stored: Research | None) -> None:
        self._stored = stored
        self.asked: list[tuple[str, datetime]] = []

    async def find_by_fingerprint(
        self, *, fingerprint: str, not_before: datetime
    ) -> Research | None:
        self.asked.append((fingerprint, not_before))
        if self._stored is None:
            return None
        if self._stored.plan_fingerprint != fingerprint:
            return None
        if self._stored.created_at < not_before:
            return None
        return self._stored


def _plan(**overrides: object) -> ResearchPlan:
    fields: dict[str, object] = {
        "normalized_query": "best national parks for avoiding crowds",
        "scope": GeoScope(type="country", value="United States"),
        "entity_granularity": EntityType.PARK,
        "granularity_confidence": 0.9,
        "topic": "national parks",
        "criteria": ["uncrowded"],
    }
    fields.update(overrides)
    return ResearchPlan.model_validate(fields)


def _result(name: str = "Great Basin") -> Result:
    return Result(
        entity_id=f"park:{name.lower().replace(' ', '-')}",
        entity_name=name,
        supporter_count=41,
        share=0.36,
        respondent_pool_size=114,
        discussion_count=27,
        weighted_score=38.4,
        confidence=0.88,
    )


def _stored_answer(
    *,
    status: ResearchStatus = ResearchStatus.COMPLETED,
    created_at: datetime = NOW - timedelta(days=30),
    plan: ResearchPlan | None = None,
    reused: ReusedAnswer | None = None,
) -> Research:
    plan = plan or _plan()
    research = Research(
        original_query="Best national parks for avoiding crowds?",
        normalized_query=plan.normalized_query,
        created_at=created_at,
        status=status,
        results=[_result()],
        weak_results=[_result("Congaree")],
        statistics={"posts_analyzed": 27, "llm_calls": 131},
        plan=plan,
        plan_fingerprint=plan_fingerprint(plan),
        reused=reused,
    )
    research.diagnostics.record_suppression(
        step="triage", reason=SuppressionReason.TRIAGE_EXCLUDED, count=4
    )
    return research


def _context(
    *,
    archive: _Archive | None,
    plan: ResearchPlan | None = None,
    config: ResearchConfig | None = None,
) -> PipelineContext:
    research = Research(
        original_query="which national parks are least crowded",
        created_at=NOW,
        status=ResearchStatus.DISCOVERING,
        research_config=config or ResearchConfig(),
    )
    context = PipelineContext(
        research=research,
        source=_ForbiddenSource(),
        search=_ForbiddenSearch(),
        llm=_ForbiddenLLM(),
        archive=archive,
    )
    context.data["plan"] = plan or _plan()
    return context


async def test_every_run_stores_the_key_it_could_be_found_by() -> None:
    """Even a miss leaves the run reusable — otherwise the first ask is never repaid."""
    plan = _plan()
    context = await AnswerReuseStep().run(_context(archive=_Archive(None), plan=plan))

    assert context.research.plan == plan
    assert context.research.plan_fingerprint == plan_fingerprint(plan)
    assert context.research.reused is None
    assert context.answered is False


async def test_a_matching_recent_completed_run_answers_the_question() -> None:
    stored = _stored_answer()

    context = await AnswerReuseStep().run(_context(archive=_Archive(stored)))

    assert context.answered is True
    assert context.research.status is ResearchStatus.COMPLETED
    assert [result.entity_name for result in context.research.results] == ["Great Basin"]
    assert [result.entity_name for result in context.research.weak_results] == ["Congaree"]
    assert context.research.reused == ReusedAnswer(
        research_id=stored.id, answered_at=stored.created_at
    )


async def test_a_differently_worded_question_hits_the_same_run() -> None:
    """Plan §2.15's headline claim, and the reason the key is the plan."""
    stored = _stored_answer(plan=_plan(normalized_query="Best National Parks for avoiding crowds?"))

    context = await AnswerReuseStep().run(_context(archive=_Archive(stored)))

    assert context.answered is True
    assert context.research.reused is not None
    assert context.research.reused.research_id == stored.id


async def test_a_question_with_different_criteria_does_not_hit() -> None:
    stored = _stored_answer(plan=_plan(criteria=["cheap"]))

    context = await AnswerReuseStep().run(_context(archive=_Archive(stored)))

    assert context.answered is False
    assert context.research.reused is None
    assert context.research.results == []


async def test_a_question_at_a_different_granularity_does_not_hit() -> None:
    stored = _stored_answer(plan=_plan(entity_granularity=EntityType.STATE))

    context = await AnswerReuseStep().run(_context(archive=_Archive(stored)))

    assert context.answered is False


async def test_a_question_in_a_different_scope_does_not_hit() -> None:
    stored = _stored_answer(plan=_plan(scope=GeoScope(type="country", value="Canada")))

    context = await AnswerReuseStep().run(_context(archive=_Archive(stored)))

    assert context.answered is False


async def test_an_answer_older_than_the_window_is_never_reused() -> None:
    stored = _stored_answer(created_at=NOW - timedelta(days=200))

    context = await AnswerReuseStep().run(_context(archive=_Archive(stored)))

    assert context.answered is False
    assert context.research.reused is None


async def test_the_window_is_config_and_the_step_asks_within_it() -> None:
    archive = _Archive(None)
    config = ResearchConfig(reuse=ReuseConfig(window_days=7))

    await AnswerReuseStep().run(_context(archive=archive, config=config))

    assert archive.asked == [(plan_fingerprint(_plan()), NOW - timedelta(days=7))]


async def test_a_partial_run_may_not_answer_for_a_later_question() -> None:
    """Plan §7.1 gives ``completed_partial`` its own wording for a reason.

    A copy of it cannot say that *its own* corpus was cut short, so reusing
    one would spread a single bad afternoon across every later asking —
    §0.1 rule 4 broken at a distance.
    """
    stored = _stored_answer(status=ResearchStatus.COMPLETED_PARTIAL)

    context = await AnswerReuseStep().run(_context(archive=_Archive(stored)))

    assert context.answered is False
    assert context.research.results == []


async def test_a_degraded_run_may_not_answer_for_a_later_question() -> None:
    stored = _stored_answer(status=ResearchStatus.COMPLETED_DEGRADED)

    assert (await AnswerReuseStep().run(_context(archive=_Archive(stored)))).answered is False


async def test_a_cancelled_run_may_not_answer_for_a_later_question() -> None:
    stored = _stored_answer(status=ResearchStatus.CANCELLED)

    assert (await AnswerReuseStep().run(_context(archive=_Archive(stored)))).answered is False


async def test_a_failed_run_may_not_answer_for_a_later_question() -> None:
    stored = _stored_answer(status=ResearchStatus.FAILED)
    stored.diagnostics.record_failure(
        kind=FailureKind.UNEXPECTED_ERROR, step="worker", detail="boom"
    )

    assert (await AnswerReuseStep().run(_context(archive=_Archive(stored)))).answered is False


async def test_a_reused_answer_may_not_itself_be_reused() -> None:
    """Otherwise the date drifts a hop at a time until an old answer looks new."""
    original = uuid4()
    stored = _stored_answer(
        reused=ReusedAnswer(research_id=original, answered_at=NOW - timedelta(days=150))
    )

    context = await AnswerReuseStep().run(_context(archive=_Archive(stored)))

    assert context.answered is False


async def test_a_fresh_run_never_consults_the_cache() -> None:
    """Plan §2.15 rule 2. Not "looks and declines" — does not look."""
    archive = _Archive(_stored_answer())
    config = ResearchConfig(reuse=ReuseConfig(enabled=False))

    context = await AnswerReuseStep().run(_context(archive=archive, config=config))

    assert archive.asked == []
    assert context.answered is False
    assert context.research.plan_fingerprint == plan_fingerprint(_plan())


async def test_a_run_with_no_archive_does_the_work_itself() -> None:
    context = await AnswerReuseStep().run(_context(archive=None))

    assert context.answered is False
    assert context.research.plan_fingerprint is not None


async def test_a_rejected_question_has_no_key_and_looks_nothing_up() -> None:
    """Query Understanding left no plan, so there is nothing to match on."""
    archive = _Archive(_stored_answer())
    context = _context(archive=archive)
    del context.data["plan"]
    context.research.status = ResearchStatus.REJECTED

    result = await AnswerReuseStep().run(context)

    assert archive.asked == []
    assert result.research.plan_fingerprint is None
    assert result.answered is False


async def test_the_answer_travels_with_the_statistics_and_diagnostics_that_earned_it() -> None:
    """The numbers describe the answer, not the copying.

    A reused run that showed the ranking but dropped the suppressions would
    present a corpus-limited answer as an unqualified one (plan §0.1 rule 2).
    """
    stored = _stored_answer()

    context = await AnswerReuseStep().run(_context(archive=_Archive(stored)))

    assert context.research.statistics["posts_analyzed"] == 27
    assert [s.reason for s in context.research.diagnostics.suppressions] == [
        SuppressionReason.TRIAGE_EXCLUDED
    ]
    assert context.research.normalized_query == stored.normalized_query


async def test_the_copy_does_not_share_state_with_the_run_it_came_from() -> None:
    """Two rows, two lives: editing one must never rewrite history in the other."""
    stored = _stored_answer()

    context = await AnswerReuseStep().run(_context(archive=_Archive(stored)))
    assert context.answered is True

    context.research.results.append(_result("Isle Royale"))
    context.research.statistics["posts_analyzed"] = 0
    context.research.diagnostics.record_suppression(
        step="test", reason=SuppressionReason.TRIAGE_NO_VERDICT, count=1
    )

    assert len(stored.results) == 1
    assert stored.statistics["posts_analyzed"] == 27
    assert len(stored.diagnostics.suppressions) == 1
