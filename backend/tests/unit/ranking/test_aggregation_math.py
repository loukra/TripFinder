"""Golden datasets for the metric (plan §4, §9, §10 Phase 11 acceptance).

Every expected number here is hand-calculated, not derived from the code
under test — this is the suite plan §9 calls "the single most valuable ...
because it protects the number the user actually reads."
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from builders.phase7 import make_comment
from tripfinder.domain.config import RankingConfig, RankingKey
from tripfinder.domain.models import Comment, Entity, EntityType, Opinion, Stance
from tripfinder.ranking.aggregation import aggregate_and_rank

NOW = datetime(2026, 9, 10, tzinfo=UTC)

ALASKA = Entity(canonical_id="state:alaska", canonical_name="Alaska", entity_type=EntityType.STATE)
OREGON = Entity(canonical_id="state:oregon", canonical_name="Oregon", entity_type=EntityType.STATE)
NEW_MEXICO = Entity(
    canonical_id="state:new_mexico", canonical_name="New Mexico", entity_type=EntityType.STATE
)


def opinion(
    comment_id: str,
    user_id: str,
    entity: Entity,
    *,
    strength: float = 0.8,
    relevance: float = 0.8,
    confidence: float = 0.8,
    timestamp: datetime = NOW,
) -> Opinion:
    return Opinion(
        comment_id=comment_id,
        user_id=user_id,
        entity_id=entity.canonical_id,
        stance=Stance.POSITIVE,
        strength=strength,
        relevance=relevance,
        timestamp=timestamp,
        confidence=confidence,
    )


def comment(comment_id: str, *, document_id: str = "d1", user_id: str = "u1") -> Comment:
    return make_comment(comment_id, document_id=document_id, user_id=user_id)


def comments_for(opinions: Sequence[Opinion], *, document_id: str = "d1") -> list[Comment]:
    """One matching ``Comment`` per opinion, all from one document unless overridden."""
    return [comment(o.comment_id, document_id=document_id, user_id=o.user_id) for o in opinions]


class TestSupporterCountsSharesAndDenominator:
    """plan §4.1-4.2: the worked example's shape, hand-calculated."""

    def test_counts_and_shares_match_by_hand(self) -> None:
        # 3 Alaska supporters, 2 Oregon supporters, 5 distinct people total.
        opinions = [
            opinion("c1", "u1", ALASKA),
            opinion("c2", "u2", ALASKA),
            opinion("c3", "u3", ALASKA),
            opinion("c4", "u4", OREGON),
            opinion("c5", "u5", OREGON),
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA, OREGON],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        assert outcome.respondent_pool_size == 5
        by_id = {r.entity_id: r for r in outcome.strong}
        assert by_id["state:alaska"].supporter_count == 3
        assert by_id["state:alaska"].share == 3 / 5
        assert by_id["state:alaska"].respondent_pool_size == 5
        assert by_id["state:oregon"].supporter_count == 2
        assert by_id["state:oregon"].share == 2 / 5

    def test_a_user_recommending_two_entities_counts_in_both_shares(self) -> None:
        """Shares need not sum to 100% (plan §2.1) — one person, two entities."""
        opinions = [
            opinion("c1", "u1", ALASKA),
            opinion("c2", "u1", OREGON),
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA, OREGON],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        assert outcome.respondent_pool_size == 1
        shares = {r.entity_id: r.share for r in outcome.strong}
        assert shares == {"state:alaska": 1.0, "state:oregon": 1.0}


class TestRelevanceThreshold:
    """plan §4.1: aggregation's own gate, left open by Phase 10."""

    def test_an_opinion_below_the_threshold_never_counts(self) -> None:
        opinions = [opinion("c1", "u1", ALASKA, relevance=0.2)]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA],
            config=RankingConfig(relevance_threshold=0.5),
            now=NOW,
        )

        assert outcome.strong == []
        assert outcome.weak == []
        assert outcome.respondent_pool_size == 0
        assert outcome.opinions_below_relevance_threshold == 1

    def test_a_qualifying_opinion_still_counts_alongside_a_dropped_one(self) -> None:
        opinions = [
            opinion("c1", "u1", ALASKA, relevance=0.9),
            opinion("c2", "u2", ALASKA, relevance=0.1),
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA],
            config=RankingConfig(relevance_threshold=0.5, minimum_independent_users=1),
            now=NOW,
        )

        assert outcome.opinions_below_relevance_threshold == 1
        [result] = outcome.strong
        assert result.supporter_count == 1
        assert outcome.respondent_pool_size == 1


class TestTimeWeight:
    """plan §4.2: ``max(minWeight, 1.0 - decayPerYear * ageYears(c))``."""

    def test_default_decay_at_five_years(self) -> None:
        opinions = [
            opinion(
                "c1",
                "u1",
                ALASKA,
                strength=1.0,
                relevance=1.0,
                timestamp=NOW - timedelta(days=5 * 365.25),
            )
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        [result] = outcome.strong
        assert result.weighted_score == pytest.approx(0.5, abs=1e-3)  # 1 - 0.10 * 5

    def test_decay_floors_at_min_weight(self) -> None:
        opinions = [
            opinion(
                "c1",
                "u1",
                ALASKA,
                strength=1.0,
                relevance=1.0,
                timestamp=NOW - timedelta(days=20 * 365.25),
            )
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        [result] = outcome.strong
        assert result.weighted_score == 0.3  # floor, not 1 - 0.10*20 = -1.0

    def test_weighted_score_never_exceeds_supporter_count(self) -> None:
        opinions = [
            opinion("c1", "u1", ALASKA, strength=1.0, relevance=1.0, timestamp=NOW),
            opinion("c2", "u2", ALASKA, strength=1.0, relevance=1.0, timestamp=NOW),
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        [result] = outcome.strong
        assert result.weighted_score <= result.supporter_count


class TestRankingOrderAndTiebreaks:
    """plan §4.3: descending on the ranking key, then the other metric, then id."""

    def test_default_sorts_by_supporter_count_descending(self) -> None:
        opinions = [
            opinion("c1", "u1", ALASKA),
            opinion("c2", "u2", ALASKA),
            opinion("c3", "u3", OREGON),
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA, OREGON],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        assert [r.entity_id for r in outcome.strong] == ["state:alaska", "state:oregon"]

    def test_a_supporter_count_tie_breaks_on_weighted_score(self) -> None:
        opinions = [
            opinion("c1", "u1", ALASKA, strength=1.0, relevance=1.0),
            opinion("c2", "u2", OREGON, strength=0.2, relevance=0.5),
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA, OREGON],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        assert [r.entity_id for r in outcome.strong] == ["state:alaska", "state:oregon"]

    def test_a_full_tie_breaks_on_canonical_id_ascending(self) -> None:
        opinions = [
            opinion("c1", "u1", OREGON, strength=0.8, relevance=0.8),
            opinion("c2", "u2", ALASKA, strength=0.8, relevance=0.8),
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA, OREGON],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        # "state:alaska" < "state:oregon" lexicographically.
        assert [r.entity_id for r in outcome.strong] == ["state:alaska", "state:oregon"]

    def test_weighted_score_ranking_key_reorders_results(self) -> None:
        opinions = [
            opinion("c1", "u1", ALASKA, strength=0.1, relevance=0.5),
            opinion("c2", "u2", ALASKA, strength=0.1, relevance=0.5),
            opinion("c3", "u3", OREGON, strength=1.0, relevance=1.0),
        ]
        config = RankingConfig(minimum_independent_users=1, ranking_key=RankingKey.WEIGHTED_SCORE)
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA, OREGON],
            config=config,
            now=NOW,
        )

        # Alaska: 2 supporters but weighted_score 0.05 each -> 0.10 total.
        # Oregon: 1 supporter, weighted_score 1.0. Oregon ranks first on
        # weighted_score even though it has fewer supporters.
        assert [r.entity_id for r in outcome.strong] == ["state:oregon", "state:alaska"]

    def test_identical_input_yields_identical_output(self) -> None:
        opinions = [
            opinion("c1", "u1", ALASKA),
            opinion("c2", "u2", OREGON),
            opinion("c3", "u3", ALASKA),
        ]
        config = RankingConfig(minimum_independent_users=1)
        first = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA, OREGON],
            config=config,
            now=NOW,
        )
        second = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA, OREGON],
            config=config,
            now=NOW,
        )

        assert first.strong == second.strong
        assert first.weak == second.weak


class TestStrongWeakThresholdsAndCap:
    """plan §4.4: strong at the independent-user floor, capped, never padded."""

    def test_below_threshold_entities_land_in_weak_not_dropped(self) -> None:
        opinions = [opinion("c1", "u1", ALASKA)]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA],
            config=RankingConfig(minimum_independent_users=5),
            now=NOW,
        )

        assert outcome.strong == []
        [weak] = outcome.weak
        assert weak.entity_id == "state:alaska"
        assert weak.supporter_count == 1

    def test_qualifying_entities_beyond_the_cap_fall_through_to_weak(self) -> None:
        entities = [ALASKA, OREGON, NEW_MEXICO]
        opinions = [
            opinion("c1", "u1", ALASKA),
            opinion("c2", "u2", OREGON),
            opinion("c3", "u3", NEW_MEXICO),
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=entities,
            config=RankingConfig(minimum_independent_users=1, max_strong_results=2),
            now=NOW,
        )

        assert len(outcome.strong) == 2
        assert len(outcome.weak) == 1
        # Nothing computed disappears: every entity is in exactly one bucket.
        all_ids = {r.entity_id for r in outcome.strong} | {r.entity_id for r in outcome.weak}
        assert all_ids == {e.canonical_id for e in entities}

    def test_never_pads_when_fewer_than_the_cap_qualify(self) -> None:
        opinions = [opinion("c1", "u1", ALASKA)]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA],
            config=RankingConfig(minimum_independent_users=1, max_strong_results=5),
            now=NOW,
        )

        assert len(outcome.strong) == 1


class TestTopicalThreadUsersNeverReachP:
    """plan §4.5, §9: the regression a partial exclusion would reintroduce.

    ``aggregate_and_rank`` only ever sees ``counted_opinions`` — the corpus
    upstream steps have already restricted to polling-context comments
    (plan §4.5). A topical thread's opinions are never passed in here at
    all, which is exactly the invariant this fixture pins down: a user whose
    only opinion came from a topical (excluded) thread contributes to
    neither the numerator nor the denominator.
    """

    def test_a_topical_only_user_is_absent_from_pool_and_every_supporter_count(self) -> None:
        # u1, u2 answered the polling thread "most underrated state?" and
        # both named Alaska. u3 only posted in a topical Alaska thread
        # ("Alaska is so underrated, right?") — that opinion is evidence,
        # never passed to aggregation at all.
        polling_opinions = [
            opinion("c1", "u1", ALASKA),
            opinion("c2", "u2", ALASKA),
        ]
        # u3's topical-thread opinion is deliberately NOT included in
        # counted_opinions — mirroring what plan §4.5 requires upstream.

        outcome = aggregate_and_rank(
            counted_opinions=polling_opinions,
            comments=comments_for(polling_opinions, document_id="polling_thread"),
            entities=[ALASKA],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        assert outcome.respondent_pool_size == 2
        [result] = outcome.strong
        assert result.supporter_count == 2
        assert result.share == 1.0  # not diluted by u3, who never appears

    def test_a_user_with_both_a_polling_vote_and_a_topical_mention_counts_once(self) -> None:
        """The same person can hold a real vote and an excluded mention — only
        the vote may ever reach this module, and it counts exactly once."""
        opinions = [
            opinion("c1", "u1", ALASKA),  # u1's counted, polling-context vote
            opinion("c2", "u2", OREGON),
        ]
        # u1 also posted in a topical Oregon thread — that opinion is
        # evidence-only and is never part of counted_opinions.

        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA, OREGON],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        assert outcome.respondent_pool_size == 2
        by_id = {r.entity_id: r for r in outcome.strong}
        assert by_id["state:oregon"].supporter_count == 1


class TestDiscussionCountAndEvidencePermalinks:
    def test_discussion_count_is_distinct_source_documents(self) -> None:
        opinions = [
            opinion("c1", "u1", ALASKA),
            opinion("c2", "u2", ALASKA),
            opinion("c3", "u3", ALASKA),
        ]
        comments = [
            comment("c1", document_id="d1", user_id="u1"),
            comment("c2", document_id="d1", user_id="u2"),  # same thread as c1
            comment("c3", document_id="d2", user_id="u3"),
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments,
            entities=[ALASKA],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        [result] = outcome.strong
        assert result.discussion_count == 2

    def test_evidence_permalinks_are_deduplicated_and_sorted(self) -> None:
        opinions = [opinion("c2", "u1", ALASKA), opinion("c1", "u2", ALASKA)]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        [result] = outcome.strong
        assert result.evidence_permalinks == sorted(result.evidence_permalinks)
        assert len(result.evidence_permalinks) == 2


class TestConfidence:
    def test_confidence_is_the_mean_across_supporters(self) -> None:
        opinions = [
            opinion("c1", "u1", ALASKA, confidence=1.0),
            opinion("c2", "u2", ALASKA, confidence=0.5),
        ]
        outcome = aggregate_and_rank(
            counted_opinions=opinions,
            comments=comments_for(opinions),
            entities=[ALASKA],
            config=RankingConfig(minimum_independent_users=1),
            now=NOW,
        )

        [result] = outcome.strong
        assert result.confidence == 0.75


class TestEmptyInput:
    def test_no_opinions_yields_empty_results_with_no_division_error(self) -> None:
        outcome = aggregate_and_rank(
            counted_opinions=[],
            comments=[],
            entities=[ALASKA],
            config=RankingConfig(),
            now=NOW,
        )

        assert outcome.strong == []
        assert outcome.weak == []
        assert outcome.respondent_pool_size == 0
