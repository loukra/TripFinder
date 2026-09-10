"""User Deduplication (plan §4.6 step 9, `PROJECT.md` §16, `PROJECT.md` §27 Phase 10).

`PROJECT.md` names the cases: multiple comments by one user, multiple
threads by one user, twenty different users with identical wording, and
deleted/anonymous authors. Each has a class below, followed by the signed
stance rule and evidence-retention guarantee plan §10 adds to the table row.
"""

from __future__ import annotations

from collections.abc import Sequence

from builders.phase7 import make_comment, make_context
from tripfinder.analysis.comment_analysis import CommentAnalysis, EntityMention
from tripfinder.analysis.entity_resolution import ResolvedMention
from tripfinder.domain.models import (
    UNKNOWN_USER_ID,
    Comment,
    Entity,
    EntityType,
    Stance,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.user_deduplication import UserDeduplicationStep

ALASKA = Entity(canonical_id="state:alaska", canonical_name="Alaska", entity_type=EntityType.STATE)


def mention(
    *, stance: Stance = Stance.POSITIVE, strength: float = 0.8, raw: str = "Alaska"
) -> EntityMention:
    return EntityMention(
        raw_text=raw,
        normalized_guess=raw,
        entity_type=EntityType.STATE,
        stance=stance,
        strength=strength,
        supporting_quote="a verbatim span",
    )


def resolution(
    comment_id: str,
    *,
    entity: Entity = ALASKA,
    stance: Stance = Stance.POSITIVE,
    strength: float = 0.8,
) -> ResolvedMention:
    return ResolvedMention(
        comment_id=comment_id, mention=mention(stance=stance, strength=strength), entity=entity
    )


def analysis(
    comment_id: str, *, confidence: float = 0.8, topic: float = 0.9, criterion: float = 0.9
) -> CommentAnalysis:
    return CommentAnalysis(
        comment_id=comment_id,
        topic_relevance=topic,
        criterion_relevance=criterion,
        scope_match=True,
        overall_confidence=confidence,
        mentions=[],
        reasoning="fixture",
    )


def context_with(
    *,
    comments: Sequence[Comment],
    analyses: Sequence[CommentAnalysis],
    counted: Sequence[ResolvedMention] = (),
    evidence: Sequence[ResolvedMention] = (),
) -> PipelineContext:
    context = make_context()
    context.data["comments"] = list(comments)
    context.data["comment_analyses"] = list(analyses)
    context.data["counted_resolutions"] = list(counted)
    context.data["evidence_resolutions"] = list(evidence)
    return context


class TestOneUserOneEntity:
    """`PROJECT.md` §16: "one user + one research + one entity = at most one counted opinion"."""

    async def test_multiple_comments_by_one_user_about_one_entity_count_once(self) -> None:
        comments = [make_comment("c1", user_id="u1"), make_comment("c2", user_id="u1")]
        analyses = [analysis("c1", confidence=0.6), analysis("c2", confidence=0.9)]
        context = context_with(
            comments=comments, analyses=analyses, counted=[resolution("c1"), resolution("c2")]
        )

        await UserDeduplicationStep().run(context)

        [counted] = context.data["counted_opinions"]
        assert counted.comment_id == "c2"
        [demoted] = context.data["evidence_opinions"]
        assert demoted.comment_id == "c1"

    async def test_multiple_threads_by_one_user_still_count_once(self) -> None:
        comments = [
            make_comment("c1", document_id="d1", user_id="u1"),
            make_comment("c2", document_id="d2", user_id="u1"),
        ]
        analyses = [analysis("c1"), analysis("c2")]
        context = context_with(
            comments=comments, analyses=analyses, counted=[resolution("c1"), resolution("c2")]
        )

        await UserDeduplicationStep().run(context)

        assert len(context.data["counted_opinions"]) == 1
        assert context.research.statistics["opinions_deduplicated"] == 1

    async def test_a_different_entity_is_not_deduplicated_against(self) -> None:
        oregon = Entity(
            canonical_id="state:oregon", canonical_name="Oregon", entity_type=EntityType.STATE
        )
        comments = [make_comment("c1", user_id="u1"), make_comment("c2", user_id="u1")]
        analyses = [analysis("c1"), analysis("c2")]
        context = context_with(
            comments=comments,
            analyses=analyses,
            counted=[resolution("c1"), resolution("c2", entity=oregon)],
        )

        await UserDeduplicationStep().run(context)

        assert len(context.data["counted_opinions"]) == 2

    async def test_twenty_different_users_remain_twenty_independent_opinions(self) -> None:
        comments = [make_comment(f"c{i}", user_id=f"u{i}") for i in range(20)]
        analyses = [analysis(f"c{i}") for i in range(20)]
        context = context_with(
            comments=comments,
            analyses=analyses,
            counted=[resolution(f"c{i}") for i in range(20)],
        )

        await UserDeduplicationStep().run(context)

        assert len(context.data["counted_opinions"]) == 20
        assert context.research.statistics["opinion_holders_counted"] == 20
        assert context.research.statistics["opinions_deduplicated"] == 0


class TestDeletedAuthors:
    """An anonymized author id must not silently merge unrelated people."""

    async def test_deleted_authors_are_never_merged_with_each_other(self) -> None:
        comments = [
            make_comment("c1", user_id=UNKNOWN_USER_ID),
            make_comment("c2", user_id=UNKNOWN_USER_ID),
        ]
        analyses = [analysis("c1"), analysis("c2")]
        context = context_with(
            comments=comments, analyses=analyses, counted=[resolution("c1"), resolution("c2")]
        )

        await UserDeduplicationStep().run(context)

        assert len(context.data["counted_opinions"]) == 2
        assert context.research.statistics["opinions_deduplicated"] == 0

    async def test_a_named_user_is_still_deduplicated_alongside_deleted_ones(self) -> None:
        comments = [
            make_comment("c1", user_id=UNKNOWN_USER_ID),
            make_comment("c2", user_id="u1"),
            make_comment("c3", user_id="u1"),
        ]
        analyses = [analysis("c1"), analysis("c2"), analysis("c3")]
        context = context_with(
            comments=comments,
            analyses=analyses,
            counted=[resolution("c1"), resolution("c2"), resolution("c3")],
        )

        await UserDeduplicationStep().run(context)

        assert len(context.data["counted_opinions"]) == 2


class TestSignedStance:
    """plan §2.3: only ``positive`` counts toward supporters."""

    async def test_a_negative_stance_is_never_counted(self) -> None:
        comments = [make_comment("c1", user_id="u1")]
        analyses = [analysis("c1")]
        context = context_with(
            comments=comments, analyses=analyses, counted=[resolution("c1", stance=Stance.NEGATIVE)]
        )

        await UserDeduplicationStep().run(context)

        assert context.data["counted_opinions"] == []
        [evidence] = context.data["evidence_opinions"]
        assert evidence.stance is Stance.NEGATIVE

    async def test_mixed_and_mention_only_stances_are_evidence_not_counted(self) -> None:
        comments = [make_comment("c1", user_id="u1"), make_comment("c2", user_id="u2")]
        analyses = [analysis("c1"), analysis("c2")]
        context = context_with(
            comments=comments,
            analyses=analyses,
            counted=[
                resolution("c1", stance=Stance.MIXED),
                resolution("c2", stance=Stance.MENTION_ONLY),
            ],
        )

        await UserDeduplicationStep().run(context)

        assert context.data["counted_opinions"] == []
        assert len(context.data["evidence_opinions"]) == 2

    async def test_a_positive_and_a_negative_opinion_from_different_users_both_survive(
        self,
    ) -> None:
        """Negative opinions are counter-evidence, never discarded (plan §2.3)."""
        comments = [make_comment("c1", user_id="u1"), make_comment("c2", user_id="u2")]
        analyses = [analysis("c1"), analysis("c2")]
        context = context_with(
            comments=comments,
            analyses=analyses,
            counted=[resolution("c1"), resolution("c2", stance=Stance.NEGATIVE)],
        )

        await UserDeduplicationStep().run(context)

        assert len(context.data["counted_opinions"]) == 1
        assert len(context.data["evidence_opinions"]) == 1
        assert len(context.data["opinions"]) == 2


class TestTopicalEvidenceNeverCounts:
    """plan §4.5: a topical thread's opinions never reach the respondent pool."""

    async def test_evidence_resolutions_never_reach_counted_opinions(self) -> None:
        comments = [make_comment("c1", user_id="u1")]
        analyses = [analysis("c1")]
        context = context_with(comments=comments, analyses=analyses, evidence=[resolution("c1")])

        await UserDeduplicationStep().run(context)

        assert context.data["counted_opinions"] == []
        assert len(context.data["evidence_opinions"]) == 1

    async def test_a_topical_users_duplicate_opinion_is_not_deduplicated_against_a_counted_one(
        self,
    ) -> None:
        """Evidence-only opinions never compete for, or block, a counted slot."""
        comments = [make_comment("c1", user_id="u1"), make_comment("c2", user_id="u1")]
        analyses = [analysis("c1"), analysis("c2")]
        context = context_with(
            comments=comments,
            analyses=analyses,
            counted=[resolution("c1")],
            evidence=[resolution("c2")],
        )

        await UserDeduplicationStep().run(context)

        assert len(context.data["counted_opinions"]) == 1
        assert len(context.data["evidence_opinions"]) == 1


class TestEvidenceRetention:
    """plan §10: dedup demotes, it never drops (plan §0.1)."""

    async def test_nothing_is_dropped(self) -> None:
        comments = [
            make_comment("c1", user_id="u1"),
            make_comment("c2", user_id="u1"),
            make_comment("c3", user_id="u2"),
        ]
        analyses = [
            analysis("c1", confidence=0.5),
            analysis("c2", confidence=0.9),
            analysis("c3"),
        ]
        context = context_with(
            comments=comments,
            analyses=analyses,
            counted=[resolution("c1"), resolution("c2")],
            evidence=[resolution("c3")],
        )

        await UserDeduplicationStep().run(context)

        all_opinions = context.data["opinions"]
        assert {opinion.comment_id for opinion in all_opinions} == {"c1", "c2", "c3"}
        assert len(all_opinions) == 3


class TestOpinionFields:
    async def test_opinion_fields_are_joined_from_the_comment_and_its_analysis(self) -> None:
        comments = [make_comment("c1", user_id="u1")]
        analyses = [analysis("c1", confidence=0.8, topic=0.9, criterion=0.4)]
        context = context_with(comments=comments, analyses=analyses, counted=[resolution("c1")])

        await UserDeduplicationStep().run(context)

        [opinion] = context.data["counted_opinions"]
        assert opinion.user_id == "u1"
        assert opinion.entity_id == "state:alaska"
        assert opinion.stance is Stance.POSITIVE
        assert opinion.strength == 0.8
        assert opinion.relevance == 0.4
        assert opinion.confidence == 0.8
        assert opinion.timestamp == comments[0].created_at
        assert opinion.criteria_matches == ["underrated"]

    async def test_zero_criterion_relevance_yields_no_criteria_matches(self) -> None:
        comments = [make_comment("c1", user_id="u1")]
        analyses = [analysis("c1", criterion=0.0)]
        context = context_with(comments=comments, analyses=analyses, counted=[resolution("c1")])

        await UserDeduplicationStep().run(context)

        [opinion] = context.data["counted_opinions"]
        assert opinion.criteria_matches == []
