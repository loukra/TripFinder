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
stance rule when opinions are counted, §4.6 step 8's resolution for the
surface forms named here. Dropping evidence early would be a suppression
this step has no reason to make.

The corpus split from §4.5 survives the step: analyses of counted comments
and analyses of evidence-only comments stay in separate lists, so a topical
thread's users still cannot reach the respondent pool.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from typing import NamedTuple

from tripfinder.analysis.comment_analysis import (
    CommentAnalysis,
    CommentAnalysisBatch,
    EntityMention,
    build_comment_analysis_prompt,
)
from tripfinder.domain.models import Comment, ReasonCode, ResearchPlan, SuppressionReason
from tripfinder.pipeline.base import PipelineContext

logger = logging.getLogger(__name__)

DEFAULT_ANALYSIS_BATCH_SIZE = 20
"""Comments per structured call (plan §5)."""

DEFAULT_MAX_CONCURRENT_BATCHES = 8
"""Batches in flight at once (plan §2.12, 14.6b).

Derived, not guessed. A 20-comment batch measured 23.2 s at
``reasoning.effort=low``, and ``maxAIAnalysisItems`` of 1000 is 50 batches:
sequentially 1160 s, against an admission window of 240 s once §2.12.2's
tail reserve comes off the 300 s budget. Fitting 50 batches into that window
needs about five in flight; eight leaves headroom for batches slower than
the measured one without pushing hard into provider rate limits, which
answer with 429s that §8.1 has to account for as lost evidence.

Phase 15 tunes this against real runs. It is the kind of number that should
move once there is more than one measurement behind it.
"""


class _BatchResult(NamedTuple):
    """What one structured call produced, and what it cost in dropped evidence."""

    analyses: dict[str, CommentAnalysis]
    discarded: int
    """Items that named no comment in the batch, or named one twice."""

    fabricated: int
    """Mentions whose supporting quote was not in the comment."""

    unanswered: tuple[str, ...]
    """Comments this batch asked about and got no verdict for."""


def _batched(comments: Sequence[Comment], size: int) -> Iterator[Sequence[Comment]]:
    for start in range(0, len(comments), size):
        yield comments[start : start + size]


def _in_order(
    comments: Sequence[Comment], analyses: dict[str, CommentAnalysis]
) -> list[CommentAnalysis]:
    """The analyses for ``comments``, in their order, skipping any that are missing."""
    return [analyses[comment.id] for comment in comments if comment.id in analyses]


def _reason_code_counts(analyses: Iterable[CommentAnalysis]) -> dict[str, int]:
    """How many comments each reason code accounts for — every code, including zeros.

    The zeros are the point. A breakdown that lists only what occurred
    cannot distinguish "no comment was off topic" from "this run never got
    far enough to find out", and plan §0.1 wants a thin result to name its
    cause rather than leave the reader to infer one.

    Flat ``analysis_reason_*`` keys rather than one nested mapping, because
    ``Research.statistics`` is ``dict[str, int]`` all the way to the API and
    the database, and widening it for one breakdown would be a change to
    every reader of it.
    """
    counts = Counter(analysis.reason_code for analysis in analyses)
    return {f"analysis_reason_{code.value}": counts[code] for code in ReasonCode}


class CommentAnalysisStep:
    """Real implementation of plan §4.6 step 7."""

    name = "comment_analysis"

    def __init__(
        self,
        *,
        batch_size: int = DEFAULT_ANALYSIS_BATCH_SIZE,
        max_concurrent_batches: int = DEFAULT_MAX_CONCURRENT_BATCHES,
    ) -> None:
        self._batch_size = batch_size
        self._max_concurrent_batches = max_concurrent_batches

    async def run(self, context: PipelineContext) -> PipelineContext:
        plan: ResearchPlan = context.data["plan"]
        counted: list[Comment] = list(context.data.get("counted_comments", []))
        evidence: list[Comment] = list(context.data.get("evidence_comments", []))

        # Counted comments first, in the §4.5 budget order pre-filter left
        # them in: the corpus that decides the ranking is dispatched before
        # the corpus that only illustrates it.
        batches = list(_batched(counted + evidence, self._batch_size))
        results = await self._analyse_all(context, plan, batches)

        # Merged in batch order, never in completion order. Concurrency is
        # about when a call is *made*; two runs over the same corpus still
        # have to produce the same statistics and the same suppressions.
        analyses: dict[str, CommentAnalysis] = {}
        discarded = 0
        fabricated = 0
        unanswered: list[str] = []
        for result in results:
            analyses.update(result.analyses)
            discarded += result.discarded
            fabricated += result.fabricated
            unanswered.extend(result.unanswered)
        self._record_suppressions(context, fabricated, unanswered)

        counted_analyses = _in_order(counted, analyses)
        evidence_analyses = _in_order(evidence, analyses)
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
        statistics.update(_reason_code_counts(analyses.values()))
        return context

    async def _analyse_all(
        self,
        context: PipelineContext,
        plan: ResearchPlan,
        batches: Sequence[Sequence[Comment]],
    ) -> list[_BatchResult]:
        """Every batch, at most ``max_concurrent_batches`` of them in flight.

        The measured run spent 2245.9 s of its 2408 s here, in 50 round trips
        taken strictly one after another (plan §2.12). Nothing about the work
        required that: each batch is an independent question about a disjoint
        set of comments, so the only thing serialising them bought was
        latency.

        The ceiling is not a formality. Unbounded fan-out would put 50 calls
        at the provider at once, and the answer to that is 429s — evidence
        lost to a self-inflicted rate limit, which §8.1 would then have to
        report as a degraded run.

        Results come back in batch order, not completion order (see ``run``).
        """
        limit = asyncio.Semaphore(self._max_concurrent_batches)

        async def analyse_one(batch: Sequence[Comment]) -> _BatchResult:
            async with limit:
                return await self._analyse(context, plan, batch)

        return list(await asyncio.gather(*(analyse_one(batch) for batch in batches)))

    async def _analyse(
        self, context: PipelineContext, plan: ResearchPlan, batch: Sequence[Comment]
    ) -> _BatchResult:
        """One structured call, matched back to the comments it was asked about."""
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

        unanswered = tuple(
            comment_id for comment_id in requested if comment_id not in analyses
        )
        return _BatchResult(analyses, discarded, fabricated, unanswered)

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
                    mention.raw_text,
                    comment.id,
                )
        rejected = len(item.mentions) - len(verified)
        if rejected == 0:
            return item, 0
        return item.model_copy(update={"mentions": verified}), rejected

    def _record_suppressions(
        self, context: PipelineContext, fabricated: int, unanswered: Sequence[str]
    ) -> None:
        """Once, after every batch is in — so the record does not depend on timing."""
        diagnostics = context.research.diagnostics
        diagnostics.record_suppression(
            step=self.name,
            reason=SuppressionReason.ANALYSIS_FABRICATED_QUOTE,
            count=fabricated,
            detail="mentions discarded — the supporting quote was not in the comment",
        )
        diagnostics.record_suppression(
            step=self.name,
            reason=SuppressionReason.ANALYSIS_NO_RESULT,
            count=len(unanswered),
            detail="comments the analysis call returned no verdict for",
        )
        if unanswered:
            logger.warning("analysis: no verdict returned for %d comment(s)", len(unanswered))
