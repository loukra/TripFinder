"""User Deduplication (plan §4.6 step 9, `PROJECT.md` §16).

Entity resolution (§4.6 step 8) leaves behind :class:`ResolvedMention`
objects — a comment, the place it named, and what it thought of it. This
step turns each one into the :class:`Opinion` `PROJECT.md` §7 describes, and
enforces §16's rule:

    one user + one research + one entity = at most one counted opinion

**Only a positive stance can be counted** (plan §2.3). A comment that calls
a place overrated is real evidence — it is kept — but it is not a
recommendation, and must never inflate a supporter count. Negative, mixed
and mention-only opinions are demoted to evidence alongside every mention
from a topical thread (plan §4.5), never merged, never discarded.

**Among a user's qualifying opinions for one entity, the highest-confidence
one is counted; the rest are retained as evidence** (plan §4.1). Nothing
this step processes disappears — the "evidence retention" plan §10 names as
a deliverable holds for every opinion, not only the counted ones.

**Deleted and anonymized authors are never merged with one another.** A
source that cannot identify its authors reports them all under
:data:`UNKNOWN_USER_ID`; deduplicating on that value as written would fold
every anonymous commenter into a single voter. Nothing distinguishes them,
so each is counted as its own, independent opinion — the same accepted
trade-off the plan's risk table already makes for one person using several
accounts (plan §13).

What this step does **not** do: it does not apply plan §4.1's relevance
threshold. That gate, and the rest of the metric's math, belongs to
Aggregation (plan §4.6 step 11, ranking/aggregation.py) — the single module
plan §4 reserves for it. This step only decides identity: which opinions
exist, and which of them may compete for a supporter slot at all.
"""

from __future__ import annotations

from collections.abc import Sequence

from tripfinder.analysis.comment_analysis import CommentAnalysis
from tripfinder.analysis.entity_resolution import ResolvedMention
from tripfinder.domain.models import UNKNOWN_USER_ID, Comment, Opinion, ResearchPlan, Stance
from tripfinder.pipeline.base import PipelineContext

_DedupKey = tuple[str, str]
"""(user_id, entity_id) — the identity §16's one-counted-opinion rule keys on."""


class UserDeduplicationStep:
    """Real implementation of plan §4.6 step 9."""

    name = "user_deduplication"

    async def run(self, context: PipelineContext) -> PipelineContext:
        plan: ResearchPlan = context.data["plan"]
        comments_by_id = {comment.id: comment for comment in context.data.get("comments", [])}
        analyses_by_id = {
            analysis.comment_id: analysis
            for analysis in context.data.get("comment_analyses", [])
        }
        counted_resolutions: Sequence[ResolvedMention] = context.data.get(
            "counted_resolutions", []
        )
        evidence_resolutions: Sequence[ResolvedMention] = context.data.get(
            "evidence_resolutions", []
        )

        counted_candidates = self._build(counted_resolutions, comments_by_id, analyses_by_id, plan)
        evidence_only = self._build(evidence_resolutions, comments_by_id, analyses_by_id, plan)

        positive = [o for o in counted_candidates if o.stance is Stance.POSITIVE]
        not_positive = [o for o in counted_candidates if o.stance is not Stance.POSITIVE]
        deduped, superseded = _deduplicate(positive)

        context.data["counted_opinions"] = deduped
        context.data["evidence_opinions"] = not_positive + superseded + evidence_only
        context.data["opinions"] = deduped + not_positive + superseded + evidence_only

        statistics = context.research.statistics
        statistics["opinions_total"] = len(counted_candidates) + len(evidence_only)
        statistics["opinions_counted"] = len(deduped)
        statistics["opinions_evidence_only"] = (
            len(not_positive) + len(superseded) + len(evidence_only)
        )
        statistics["opinions_deduplicated"] = len(superseded)
        statistics["opinion_holders_counted"] = len({o.user_id for o in deduped})
        return context

    def _build(
        self,
        resolutions: Sequence[ResolvedMention],
        comments_by_id: dict[str, Comment],
        analyses_by_id: dict[str, CommentAnalysis],
        plan: ResearchPlan,
    ) -> list[Opinion]:
        return [
            _to_opinion(
                resolution,
                comments_by_id[resolution.comment_id],
                analyses_by_id[resolution.comment_id],
                plan,
            )
            for resolution in resolutions
        ]


def _to_opinion(
    resolution: ResolvedMention, comment: Comment, analysis: CommentAnalysis, plan: ResearchPlan
) -> Opinion:
    """One resolved mention, normalized into the Opinion `PROJECT.md` §7 describes.

    ``relevance`` is the minimum of §5's ``topic_relevance`` and
    ``criterion_relevance`` — a comment must address both the topic and the
    criteria to be relevant to the question asked, and §4.1 checks a single
    number against one threshold. ``criteria_matches`` is necessarily
    coarse: §5's contract reports one aggregate criterion score rather than
    a per-criterion breakdown, so a nonzero score attributes the whole plan
    of criteria rather than naming which one matched.
    """
    return Opinion(
        comment_id=comment.id,
        user_id=comment.user_id,
        entity_id=resolution.entity.canonical_id,
        stance=resolution.mention.stance,
        strength=resolution.mention.strength,
        relevance=min(analysis.topic_relevance, analysis.criterion_relevance),
        criteria_matches=list(plan.criteria) if analysis.criterion_relevance > 0.0 else [],
        timestamp=comment.created_at,
        confidence=analysis.overall_confidence,
    )


def _dedup_key(opinion: Opinion) -> _DedupKey | None:
    """The identity §16's rule is judged against, or ``None`` to never merge."""
    if opinion.user_id == UNKNOWN_USER_ID:
        return None
    return (opinion.user_id, opinion.entity_id)


def _deduplicate(opinions: Sequence[Opinion]) -> tuple[list[Opinion], list[Opinion]]:
    """`PROJECT.md` §16: at most one counted opinion per (user, entity).

    The highest-confidence opinion in each group is kept; the rest are
    superseded — retained as evidence by the caller, never dropped (plan
    §0.1). Ties break on ``comment_id`` so the choice is deterministic
    (plan §4.3's tiebreak philosophy) rather than dependent on input order.
    """
    groups: dict[_DedupKey, list[Opinion]] = {}
    order: list[_DedupKey] = []
    kept: list[Opinion] = []

    for opinion in opinions:
        key = _dedup_key(opinion)
        if key is None:
            kept.append(opinion)
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(opinion)

    superseded: list[Opinion] = []
    for key in order:
        group = sorted(groups[key], key=lambda o: (-o.confidence, o.comment_id))
        kept.append(group[0])
        superseded.extend(group[1:])
    return kept, superseded
