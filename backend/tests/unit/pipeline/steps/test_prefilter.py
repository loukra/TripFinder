"""Cheap Pre-filtering (plan §4.6 step 6), and the §4.5 corpus rule it enforces."""

from __future__ import annotations

from collections.abc import Sequence

from builders.phase7 import make_comment, make_context
from tripfinder.domain.config import PrefilterConfig, ResearchBudget, ResearchConfig
from tripfinder.domain.models import Comment, ResearchFlag, SuppressionReason
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.prefilter import CheapPrefilterStep

LONG_ENOUGH = "The Upper Peninsula of Michigan is beautiful and nobody ever goes there."


def _loaded(
    context: PipelineContext,
    *,
    polling: Sequence[Comment] = (),
    topical: Sequence[Comment] = (),
) -> PipelineContext:
    context.data["polling_comments"] = list(polling)
    context.data["topical_comments"] = list(topical)
    return context


async def test_short_comments_are_dropped_and_counted() -> None:
    context = _loaded(
        make_context(),
        polling=[
            make_comment("keep", body=LONG_ENOUGH),
            make_comment("drop", body="this"),
        ],
    )

    await CheapPrefilterStep().run(context)

    assert [comment.id for comment in context.data["counted_comments"]] == ["keep"]
    (suppression,) = [
        entry
        for entry in context.research.diagnostics.suppressions
        if entry.reason is SuppressionReason.PREFILTER_TOO_SHORT
    ]
    assert suppression.count == 1


async def test_deleted_and_removed_bodies_are_dropped() -> None:
    context = _loaded(
        make_context(),
        polling=[
            make_comment("a", body="[deleted]"),
            make_comment("b", body="[removed]"),
            make_comment("c", body="   "),
            make_comment("keep", body=LONG_ENOUGH),
        ],
    )

    await CheapPrefilterStep().run(context)

    assert [comment.id for comment in context.data["counted_comments"]] == ["keep"]
    (suppression,) = [
        entry
        for entry in context.research.diagnostics.suppressions
        if entry.reason is SuppressionReason.PREFILTER_EMPTY_BODY
    ]
    assert suppression.count == 3


async def test_the_length_floor_is_configurable() -> None:
    config = ResearchConfig(prefilter=PrefilterConfig(min_comment_characters=0))
    context = _loaded(make_context(config=config), polling=[make_comment("short", body="yes")])

    await CheapPrefilterStep().run(context)

    assert [comment.id for comment in context.data["counted_comments"]] == ["short"]


async def test_an_off_topic_but_substantive_comment_survives() -> None:
    """No keyword filtering here — semantic relevance is the §5 analysis call's job."""
    context = _loaded(
        make_context(),
        polling=[make_comment("c1", body="I once drove a van across three continents alone.")],
    )

    await CheapPrefilterStep().run(context)

    assert [comment.id for comment in context.data["counted_comments"]] == ["c1"]


class TestTheCountedCorpus:
    """Plan §4.5: numerator and denominator come from the same corpus — always."""

    async def test_topical_comments_are_kept_as_evidence_but_never_counted(self) -> None:
        context = _loaded(
            make_context(),
            polling=[make_comment("p1", user_id="voter", body=LONG_ENOUGH)],
            topical=[make_comment("t1", user_id="enthusiast", body=LONG_ENOUGH)],
        )

        await CheapPrefilterStep().run(context)

        assert [comment.id for comment in context.data["counted_comments"]] == ["p1"]
        assert [comment.id for comment in context.data["evidence_comments"]] == ["t1"]
        assert [comment.id for comment in context.data["analysis_comments"]] == ["p1", "t1"]

    async def test_a_topical_threads_users_reach_neither_the_pool_nor_the_numerator(
        self,
    ) -> None:
        """Excluding a topical thread removes its users from *both* sides of the share.

        Both are derived from ``counted_comments``, so a user who only ever
        spoke in a topical thread cannot inflate an entity's supporter count
        and cannot inflate the respondent pool that divides it. A partial
        exclusion — dropping the votes but keeping the users in `P` — is the
        defect §4.5 names, and it is unrepresentable here.
        """
        context = _loaded(
            make_context(),
            polling=[
                make_comment("p1", user_id="voter_a", body=LONG_ENOUGH),
                make_comment("p2", user_id="voter_b", body=LONG_ENOUGH),
            ],
            topical=[
                make_comment("t1", user_id="enthusiast", body=LONG_ENOUGH),
                make_comment("t2", user_id="voter_a", body=LONG_ENOUGH),
            ],
        )

        await CheapPrefilterStep().run(context)

        counted = context.data["counted_comments"]
        respondent_pool = {comment.user_id for comment in counted}
        supporters_of_any_entity = {comment.user_id for comment in counted}

        assert "enthusiast" not in respondent_pool
        assert "enthusiast" not in supporters_of_any_entity
        assert respondent_pool == {"voter_a", "voter_b"}

        # The enthusiast's words survive as evidence — they just cannot vote.
        assert "enthusiast" in {
            comment.user_id for comment in context.data["evidence_comments"]
        }


class TestAnalysisBudget:
    async def test_the_analysis_cap_is_enforced_and_recorded(self) -> None:
        config = ResearchConfig(budget=ResearchBudget(max_ai_analysis_items=2))
        context = _loaded(
            make_context(config=config),
            polling=[make_comment(f"p{index}", body=LONG_ENOUGH) for index in range(4)],
        )

        await CheapPrefilterStep().run(context)

        assert len(context.data["analysis_comments"]) == 2
        (suppression,) = [
            entry
            for entry in context.research.diagnostics.suppressions
            if entry.reason is SuppressionReason.BUDGET_MAX_AI_ANALYSIS_ITEMS
        ]
        assert suppression.count == 2
        assert ResearchFlag.BUDGET_LIMIT_REACHED in context.research.diagnostics.flags

    async def test_counted_comments_hold_their_budget_before_evidence(self) -> None:
        """Evidence may not buy analysis capacity away from the ranking corpus."""
        config = ResearchConfig(budget=ResearchBudget(max_ai_analysis_items=2))
        context = _loaded(
            make_context(config=config),
            polling=[make_comment(f"p{index}", body=LONG_ENOUGH) for index in range(2)],
            topical=[make_comment("t1", body=LONG_ENOUGH)],
        )

        await CheapPrefilterStep().run(context)

        assert [comment.id for comment in context.data["counted_comments"]] == ["p0", "p1"]
        assert context.data["evidence_comments"] == []

    async def test_evidence_takes_the_leftover_budget(self) -> None:
        config = ResearchConfig(budget=ResearchBudget(max_ai_analysis_items=3))
        context = _loaded(
            make_context(config=config),
            polling=[make_comment("p0", body=LONG_ENOUGH)],
            topical=[make_comment(f"t{index}", body=LONG_ENOUGH) for index in range(3)],
        )

        await CheapPrefilterStep().run(context)

        assert [comment.id for comment in context.data["evidence_comments"]] == ["t0", "t1"]


class TestTheBudgetIsSpreadAcrossDocuments:
    """Plan §2.12: three of eighty-one threads supplied every counted opinion."""

    def _across(self, documents: int, per_document: int) -> list[Comment]:
        return [
            make_comment(
                f"d{document}-c{index}",
                document_id=f"d{document}",
                body=LONG_ENOUGH,
                score=per_document - index,
            )
            for document in range(documents)
            for index in range(per_document)
        ]

    async def test_no_single_document_can_take_the_whole_budget(self) -> None:
        """The acceptance criterion, stated as the defect it replaces."""
        config = ResearchConfig(budget=ResearchBudget(max_ai_analysis_items=6))
        context = _loaded(make_context(config=config), polling=self._across(3, 20))

        await CheapPrefilterStep().run(context)

        documents = {
            comment.source_document_id for comment in context.data["counted_comments"]
        }
        assert documents == {"d0", "d1", "d2"}

    async def test_every_document_contributes_when_the_budget_allows_one_each(self) -> None:
        config = ResearchConfig(budget=ResearchBudget(max_ai_analysis_items=5))
        context = _loaded(make_context(config=config), polling=self._across(5, 10))

        await CheapPrefilterStep().run(context)

        documents = [
            comment.source_document_id for comment in context.data["counted_comments"]
        ]
        assert sorted(documents) == ["d0", "d1", "d2", "d3", "d4"]

    async def test_a_lopsided_corpus_still_reaches_the_small_threads(self) -> None:
        """566 + 424 + 10 was the measured shape: two giants and everything else."""
        giant = [
            make_comment(f"g{index}", document_id="giant", body=LONG_ENOUGH, score=100)
            for index in range(500)
        ]
        small = [make_comment("s0", document_id="small", body=LONG_ENOUGH, score=1)]
        config = ResearchConfig(budget=ResearchBudget(max_ai_analysis_items=10))
        context = _loaded(make_context(config=config), polling=giant + small)

        await CheapPrefilterStep().run(context)

        kept = context.data["counted_comments"]
        assert "small" in {comment.source_document_id for comment in kept}

    async def test_the_best_scoring_comments_of_a_document_are_taken_first(self) -> None:
        config = ResearchConfig(budget=ResearchBudget(max_ai_analysis_items=2))
        context = _loaded(
            make_context(config=config),
            polling=[
                make_comment("low", body=LONG_ENOUGH, score=1),
                make_comment("high", body=LONG_ENOUGH, score=99),
                make_comment("mid", body=LONG_ENOUGH, score=50),
            ],
        )

        await CheapPrefilterStep().run(context)

        assert [comment.id for comment in context.data["counted_comments"]] == ["high", "mid"]

    async def test_comments_without_a_score_keep_retrieval_order(self) -> None:
        """Unknown is not zero, but it has to sort somewhere; it invents no ranking."""
        config = ResearchConfig(budget=ResearchBudget(max_ai_analysis_items=2))
        context = _loaded(
            make_context(config=config),
            polling=[make_comment(f"c{index}", body=LONG_ENOUGH) for index in range(4)],
        )

        await CheapPrefilterStep().run(context)

        assert [comment.id for comment in context.data["counted_comments"]] == ["c0", "c1"]

    async def test_a_prefix_of_the_kept_corpus_is_already_a_broad_sample(self) -> None:
        """What makes an early stop (§2.12.2) survivable rather than lopsided."""
        config = ResearchConfig(budget=ResearchBudget(max_ai_analysis_items=12))
        context = _loaded(make_context(config=config), polling=self._across(4, 10))

        await CheapPrefilterStep().run(context)

        first_four = context.data["counted_comments"][:4]
        assert len({comment.source_document_id for comment in first_four}) == 4

    async def test_nothing_is_dropped_when_the_budget_covers_the_corpus(self) -> None:
        context = _loaded(make_context(), polling=self._across(3, 4))

        await CheapPrefilterStep().run(context)

        assert len(context.data["counted_comments"]) == 12
        assert context.research.diagnostics.flags == []


async def test_statistics_record_both_corpora() -> None:
    context = _loaded(
        make_context(),
        polling=[make_comment("p1", body=LONG_ENOUGH)],
        topical=[make_comment("t1", body=LONG_ENOUGH), make_comment("t2", body="no")],
    )

    await CheapPrefilterStep().run(context)

    assert context.research.statistics["comments_counted_corpus"] == 1
    assert context.research.statistics["comments_evidence_corpus"] == 1
    assert context.research.statistics["comments_analyzed"] == 2


async def test_an_empty_corpus_prefilters_cleanly() -> None:
    context = _loaded(make_context())

    await CheapPrefilterStep().run(context)

    assert context.data["analysis_comments"] == []
    assert context.research.diagnostics.suppressions == []
