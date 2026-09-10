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

**The §4.5 binding rule lives here.** ``counted_comments`` holds polling
comments only. Both the respondent pool `P` and every entity's supporter
set are drawn from that one list, so a topical thread's users can never
appear in one without the other. ``evidence_comments`` keeps the topical
material for explanations and counter-evidence (plan §4.5), where it cannot
touch the number.
"""

from __future__ import annotations

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


def _is_substantive(comment: Comment, config: PrefilterConfig) -> SuppressionReason | None:
    """The drop reason for a comment, or ``None`` if it survives."""
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
        counted, dropped = _truncate(counted, max_items)
        evidence, dropped_evidence = _truncate(evidence, max_items - len(counted))
        over_budget = dropped + dropped_evidence
        if over_budget:
            diagnostics.record_suppression(
                step=self.name,
                reason=SuppressionReason.BUDGET_MAX_AI_ANALYSIS_ITEMS,
                count=over_budget,
                detail=f"analysis corpus capped at {max_items} items",
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
            reason = _is_substantive(comment, config)
            if reason is None:
                kept.append(comment)
            else:
                context.research.diagnostics.record_suppression(
                    step=self.name, reason=reason, count=1
                )
        return kept


def _truncate(comments: list[Comment], limit: int) -> tuple[list[Comment], int]:
    if limit <= 0:
        return [], len(comments)
    if len(comments) <= limit:
        return comments, 0
    return comments[:limit], len(comments) - limit
