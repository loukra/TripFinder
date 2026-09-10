"""Comment Analysis (plan §4.6 step 7, §5).

The one AI pass over comment text. It reads what triage kept and pre-filter
let through, and produces a :class:`CommentAnalysis` per comment: how
relevant it is, what it names, and how warmly.

Two deterministic guards wrap the model's answer.

**Verbatim quote verification** (`PROJECT.md` §29, plan §5). Every
``supporting_quote`` must appear as an exact substring of the stored comment
body. A mention whose quote does not is discarded and counted. This is a
check, not a prompt instruction: a prompt asks the model not to invent
evidence, and this makes invented evidence unusable when it asks in vain.

**Nothing is assumed answered.** An item naming a comment we did not send is
dropped, and a comment the model skipped is recorded as suppressed — not
quietly treated as a comment with nothing to say. That distinction is plan
§0.1's whole subject: a comment with no analysis and a comment analysed as
irrelevant produce the same empty contribution to the ranking, and only one
of them is a finding.

**What this step does *not* do** is filter. Low relevance, an unusable
stance, an entity outside the scope — all are recorded faithfully and left
for the deterministic steps that own them: §4.1's relevance threshold and
stance rule when opinions are counted, §9's resolution for the normalized
guesses here. Dropping evidence early would be a suppression this step has
no reason to make.

The corpus split from §4.5 survives the step: analyses of counted comments
and analyses of evidence-only comments stay in separate lists, so a topical
thread's users still cannot reach the respondent pool.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence

from tripfinder.analysis.comment_analysis import (
    CommentAnalysis,
    CommentAnalysisBatch,
    EntityMention,
    build_comment_analysis_prompt,
)
from tripfinder.domain.models import Comment, ResearchPlan, SuppressionReason
from tripfinder.pipeline.base import PipelineContext

logger = logging.getLogger(__name__)

DEFAULT_ANALYSIS_BATCH_SIZE = 20
"""Comments per structured call (plan §5)."""


def _batched(comments: Sequence[Comment], size: int) -> Iterator[Sequence[Comment]]:
    for start in range(0, len(comments), size):
        yield comments[start : start + size]


class CommentAnalysisStep:
    """Real implementation of plan §4.6 step 7."""

    name = "comment_analysis"

    def __init__(self, *, batch_size: int = DEFAULT_ANALYSIS_BATCH_SIZE) -> None:
        self._batch_size = batch_size

    async def run(self, context: PipelineContext) -> PipelineContext:
        plan: ResearchPlan = context.data["plan"]
        counted: list[Comment] = list(context.data.get("counted_comments", []))
        evidence: list[Comment] = list(context.data.get("evidence_comments", []))

        analyses: dict[str, CommentAnalysis] = {}
        discarded = 0
        fabricated = 0

        # Counted comments first, in the §4.5 budget order pre-filter left
        # them in: the corpus that decides the ranking is analysed before the
        # corpus that only illustrates it.
        for batch in _batched(counted + evidence, self._batch_size):
            batch_analyses, batch_discarded, batch_fabricated = await self._analyse(
                context, plan, batch
            )
            analyses.update(batch_analyses)
            discarded += batch_discarded
            fabricated += batch_fabricated

        counted_analyses = [analyses[comment.id] for comment in counted if comment.id in analyses]
        evidence_analyses = [analyses[comment.id] for comment in evidence if comment.id in analyses]
        context.data["counted_analyses"] = counted_analyses
        context.data["evidence_analyses"] = evidence_analyses
        context.data["comment_analyses"] = counted_analyses + evidence_analyses

        statistics = context.research.statistics
        statistics["comments_with_analysis"] = len(analyses)
        statistics["comments_without_analysis"] = len(counted) + len(evidence) - len(analyses)
        statistics["analysis_mentions_extracted"] = sum(
            len(analysis.mentions) for analysis in analyses.values()
        )
        statistics["analysis_mentions_fabricated_quote"] = fabricated
        statistics["analysis_items_discarded"] = discarded
        return context

    async def _analyse(
        self, context: PipelineContext, plan: ResearchPlan, batch: Sequence[Comment]
    ) -> tuple[dict[str, CommentAnalysis], int, int]:
        """One structured call. Returns its analyses, items dropped, quotes rejected."""
        response = await context.llm.complete_structured(
            prompt=build_comment_analysis_prompt(plan, batch),
            response_model=CommentAnalysisBatch,
        )
        requested = {comment.id: comment for comment in batch}

        analyses: dict[str, CommentAnalysis] = {}
        discarded = 0
        fabricated = 0
        for item in response.items:
            comment = requested.get(item.comment_id)
            if comment is None:
                # An analysis of a comment this batch never contained. It
                # cannot be attributed to any evidence we hold, so it is not
                # evidence (plan §5: dropped with a reason, never coerced).
                logger.warning(
                    "analysis: dropping an item for unknown comment %s", item.comment_id
                )
                discarded += 1
                continue
            if item.comment_id in analyses:
                logger.warning(
                    "analysis: dropping a duplicate item for comment %s", item.comment_id
                )
                discarded += 1
                continue
            analysis, rejected = self._verify_quotes(item, comment)
            analyses[item.comment_id] = analysis
            fabricated += rejected

        self._record_suppressions(context, requested, analyses, fabricated)
        return analyses, discarded, fabricated

    def _verify_quotes(
        self, item: CommentAnalysis, comment: Comment
    ) -> tuple[CommentAnalysis, int]:
        """Keep only the mentions whose quote really appears in the comment body."""
        verified: list[EntityMention] = []
        for mention in item.mentions:
            if mention.supporting_quote in comment.body:
                verified.append(mention)
            else:
                logger.warning(
                    "analysis: discarding a mention of %r in comment %s — "
                    "its supporting quote is not in the comment body",
                    mention.normalized_guess,
                    comment.id,
                )
        rejected = len(item.mentions) - len(verified)
        if rejected == 0:
            return item, 0
        return item.model_copy(update={"mentions": verified}), rejected

    def _record_suppressions(
        self,
        context: PipelineContext,
        requested: dict[str, Comment],
        analyses: dict[str, CommentAnalysis],
        fabricated: int,
    ) -> None:
        diagnostics = context.research.diagnostics
        diagnostics.record_suppression(
            step=self.name,
            reason=SuppressionReason.ANALYSIS_FABRICATED_QUOTE,
            count=fabricated,
            detail="mentions discarded — the supporting quote was not in the comment",
        )
        missing = [comment_id for comment_id in requested if comment_id not in analyses]
        diagnostics.record_suppression(
            step=self.name,
            reason=SuppressionReason.ANALYSIS_NO_RESULT,
            count=len(missing),
            detail="comments the analysis call returned no verdict for",
        )
        if missing:
            logger.warning("analysis: no verdict returned for %d comment(s)", len(missing))
