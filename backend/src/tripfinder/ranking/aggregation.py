"""The metric — exact specification (plan §4).

This is the **single module** plan §4 reserves for the headline number. Every
formula in plan §4.2-4.4 is implemented here, once, so it can be tested to
the decimal and never drifts out of sync with a second copy elsewhere.

**Inputs are already an identity-settled corpus.** Entity Resolution (plan
§4.6 step 8) and User Deduplication (step 9, ``pipeline/steps/
user_deduplication.py``) have already: merged surface forms to canonical
entities, kept only ``stance == positive`` opinions, and reduced each
``(user, entity)`` pair to its single highest-confidence opinion. This
module's own job, per plan §4.1, is the one gate those steps explicitly
leave open — ``relevance >= relevanceThreshold`` — plus the arithmetic and
the ranking.

**Why a topical thread's users cannot leak in here.** ``counted_opinions``
is exactly the polling-context corpus (plan §4.5) — that split happens
upstream, in Cheap Pre-filtering (``pipeline/steps/prefilter.py``), before a
single comment reaches analysis. The respondent pool ``P`` in this module is
computed **only** from ``counted_opinions``, never widened with anything
else, so a partial exclusion that plan §4.5 warns about (a thread's votes
excluded but its users left in `P`) cannot reappear here even if it did
upstream — belt and suspenders for the regression plan §0.1 calls out by
name.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from tripfinder.domain.config import RankingConfig, RankingKey
from tripfinder.domain.models import Comment, Entity, Opinion, Result

_DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class AggregationOutcome:
    """Every entity's numbers, ranked and split at the strong/weak line (plan §4.4).

    ``strong`` and ``weak`` partition every entity that had at least one
    qualifying opinion — nothing computed is dropped. ``strong`` is capped at
    ``config.max_strong_results``; entities that rank below the cap land in
    ``weak`` alongside those below ``minimum_independent_users``, in the same
    sort order.
    """

    strong: list[Result]
    weak: list[Result]
    respondent_pool_size: int
    qualifying_opinions: int
    opinions_below_relevance_threshold: int


def aggregate_and_rank(
    counted_opinions: Sequence[Opinion],
    comments: Sequence[Comment],
    entities: Sequence[Entity],
    config: RankingConfig,
    *,
    now: datetime,
) -> AggregationOutcome:
    """Compute every entity's counts and score, then rank and threshold them.

    ``comments`` is used only to resolve each opinion's ``source_document_id``
    (for ``discussion_count`` and evidence permalinks) and needs no filtering
    of its own — every opinion here already came from a real comment.
    """
    qualifying = [o for o in counted_opinions if o.relevance >= config.relevance_threshold]
    below_threshold = len(counted_opinions) - len(qualifying)

    pool_size = len({opinion.user_id for opinion in qualifying})
    entities_by_id = {entity.canonical_id: entity for entity in entities}
    comments_by_id = {comment.id: comment for comment in comments}

    by_entity: dict[str, list[Opinion]] = defaultdict(list)
    for opinion in qualifying:
        by_entity[opinion.entity_id].append(opinion)

    results = [
        _to_result(entities_by_id[entity_id], opinions, comments_by_id, pool_size, config, now=now)
        for entity_id, opinions in by_entity.items()
    ]
    results.sort(key=_sort_key(config.ranking_key))

    strong_candidates = [
        result for result in results if result.supporter_count >= config.minimum_independent_users
    ]
    strong = strong_candidates[: config.max_strong_results]
    strong_ids = {result.entity_id for result in strong}
    weak = [result for result in results if result.entity_id not in strong_ids]

    return AggregationOutcome(
        strong=strong,
        weak=weak,
        respondent_pool_size=pool_size,
        qualifying_opinions=len(qualifying),
        opinions_below_relevance_threshold=below_threshold,
    )


def _to_result(
    entity: Entity,
    opinions: Sequence[Opinion],
    comments_by_id: dict[str, Comment],
    pool_size: int,
    config: RankingConfig,
    *,
    now: datetime,
) -> Result:
    """One entity's row. ``opinions`` holds at most one per supporter (plan §4.1),
    so ``weightedScore``'s "max over that user's comments" (plan §4.2) has
    nothing left to max over — each supporter contributes exactly one term.
    """
    supporter_count = len({opinion.user_id for opinion in opinions})
    weighted_score = sum(
        opinion.strength * opinion.relevance * _time_weight(opinion.timestamp, now, config)
        for opinion in opinions
    )
    supporting_comments = [
        comments_by_id[opinion.comment_id]
        for opinion in opinions
        if opinion.comment_id in comments_by_id
    ]
    document_ids = {comment.source_document_id for comment in supporting_comments}
    permalinks = sorted({comment.permalink for comment in supporting_comments}, key=str)
    confidence = sum(opinion.confidence for opinion in opinions) / len(opinions)

    return Result(
        entity_id=entity.canonical_id,
        entity_name=entity.canonical_name,
        supporter_count=supporter_count,
        share=supporter_count / pool_size if pool_size else 0.0,
        respondent_pool_size=pool_size,
        discussion_count=len(document_ids),
        weighted_score=weighted_score,
        confidence=confidence,
        evidence_permalinks=permalinks,
    )


def _time_weight(timestamp: datetime, now: datetime, config: RankingConfig) -> float:
    """``max(minWeight, 1.0 - decayPerYear * ageYears(c))`` (plan §4.2)."""
    age_years = max(0.0, (now - timestamp).days / _DAYS_PER_YEAR)
    return max(config.min_weight, 1.0 - config.decay_per_year * age_years)


def _sort_key(ranking_key: RankingKey) -> Callable[[Result], tuple[float, float, str]]:
    """Descending on ``ranking_key``, then the other metric, then ``canonicalId``
    ascending (plan §4.3) — the tiebreak that makes ordering deterministic.
    """

    def key(result: Result) -> tuple[float, float, str]:
        primary, secondary = (
            (result.weighted_score, float(result.supporter_count))
            if ranking_key is RankingKey.WEIGHTED_SCORE
            else (float(result.supporter_count), result.weighted_score)
        )
        return (-primary, -secondary, result.entity_id)

    return key
