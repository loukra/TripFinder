"""Cheap Pre-filtering (plan §4.6 step 6).

Heuristics only; embeddings are deferred. The heuristics measure
*substance*, never *topic*: a keyword filter here would drop the
differently-worded-but-equivalent comments Phase 8 exists to catch, and an
over-strict filter starving the corpus is precisely the failure plan §0.1
forbids. Whether a comment answers the question is the §5 analysis call's
job.

The step also enforces ``maxAIAnalysisItems`` — the last bound before the
expensive step — and keeps the counted corpus separate from the evidence
corpus.

**How the budget is spent is a measurement decision, not a detail** (plan
§2.12). It used to be "the first N comments in document order", and in the
measured run that meant three of eighty-one surviving threads supplied every
counted opinion. Threads four to eighty-one contributed nothing. Raising the
budget would not have fixed it — it would have bought the first fifteen
threads instead of the first three — because each thread is a different
*population*: r/AskAnAmerican, r/hiking and r/mountainbiking are not the same
people answering. Sampling three threads samples three communities, and it
silently capped ``discussion_count``, which §4.2 uses to signal corroboration
across independent discussions. The measured top result's "3 threads" was the
ceiling, not a finding.

**The §4.5 binding rule lives here.** ``counted_comments`` holds polling
comments only. Both the respondent pool `P` and every entity's supporter
set are drawn from that one list, so a topical thread's users can never
appear in one without the other. ``evidence_comments`` keeps the topical
material for explanations and counter-evidence (plan §4.5), where it cannot
touch the number.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from tripfinder.domain.config import PrefilterConfig
from tripfinder.domain.models import (
    Comment,
    ResearchFlag,
    ResearchStatus,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext

_REMOVED_BODIES = frozenset({"[deleted]", "[removed]"})


def drop_reason(comment: Comment, config: PrefilterConfig) -> SuppressionReason | None:
    """Why this comment is not substantive enough to analyse, or ``None`` if it is."""
    body = comment.body.strip()
    if not body or body.lower() in _REMOVED_BODIES:
        return SuppressionReason.PREFILTER_EMPTY_BODY
    if len(body) < config.min_comment_characters:
        return SuppressionReason.PREFILTER_TOO_SHORT
    return None


class CheapPrefilterStep:
    """Real implementation of plan §4.6 step 6."""

    name = "cheap_prefilter"

    async def run(self, context: PipelineContext) -> PipelineContext:
        config = context.research.research_config.prefilter
        max_items = context.research.research_config.budget.max_ai_analysis_items
        diagnostics = context.research.diagnostics

        counted = self._filter(context, context.data.get("polling_comments", []), config)
        evidence = self._filter(context, context.data.get("topical_comments", []), config)

        # Counted comments hold their budget first — evidence cannot buy
        # analysis capacity away from the corpus that decides the ranking.
        counted, dropped = _allocate(counted, max_items)
        evidence, dropped_evidence = _allocate(evidence, max_items - len(counted))
        over_budget = dropped + dropped_evidence
        if over_budget:
            diagnostics.record_suppression(
                step=self.name,
                reason=SuppressionReason.BUDGET_MAX_AI_ANALYSIS_ITEMS,
                count=over_budget,
                detail=(
                    f"analysis corpus capped at {max_items} items, "
                    "spread across every document"
                ),
            )
            diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)

        context.data["counted_comments"] = counted
        context.data["evidence_comments"] = evidence
        context.data["analysis_comments"] = counted + evidence

        statistics = context.research.statistics
        statistics["comments_counted_corpus"] = len(counted)
        statistics["comments_evidence_corpus"] = len(evidence)
        statistics["comments_analyzed"] = len(counted) + len(evidence)
        context.research.status = ResearchStatus.ANALYZING
        return context

    def _filter(
        self, context: PipelineContext, comments: Sequence[Comment], config: PrefilterConfig
    ) -> list[Comment]:
        kept: list[Comment] = []
        for comment in comments:
            reason = drop_reason(comment, config)
            if reason is None:
                kept.append(comment)
            else:
                context.research.diagnostics.record_suppression(
                    step=self.name, reason=reason, count=1
                )
        return kept


def _allocate(comments: list[Comment], limit: int) -> tuple[list[Comment], int]:
    """Spend ``limit`` across every document, best comments first.

    One round at a time: each document gives up its highest-scoring
    unspent comment, then the next, until the budget runs out. A document
    with 566 comments and a document with 4 therefore reach analysis
    together, and no thread can take the whole budget while others get none
    (plan §2.12).

    **The returned order is load-bearing, not incidental.** Round-robin means
    any prefix of this list is already a broad sample, so a run that stops
    early — §2.12.2's admission deadline, or a lost batch — still has
    something to say about most threads rather than everything about three.

    Ties, and comments whose source reported no score, keep the order
    retrieval left them in: unknown is not zero, but it has to sort
    somewhere, and "as retrieved" invents no ranking of its own.
    """
    if limit <= 0:
        return [], len(comments)
    if len(comments) <= limit:
        return comments, 0

    by_document: dict[str, list[Comment]] = defaultdict(list)
    for comment in comments:
        by_document[comment.source_document_id].append(comment)
    queues = [
        sorted(document, key=lambda comment: -(comment.score or 0))
        for document in by_document.values()
    ]

    kept: list[Comment] = []
    for position in range(max(len(queue) for queue in queues)):
        for queue in queues:
            if position >= len(queue):
                continue
            kept.append(queue[position])
            if len(kept) == limit:
                return kept, len(comments) - limit
    return kept, len(comments) - len(kept)
