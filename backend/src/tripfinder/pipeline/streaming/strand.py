"""One document, carried end to end (plan §2.14.2).

A strand fetches a document's comments, caps them, pre-filters them, draws
its quota and analyses what it was granted — without waiting for any other
strand. The sequential step list did the same work document by document
anyway; nothing in retrieval, pre-filtering or the analysis prompt reads
another document, so the order between them was habit rather than a data
dependency.

**A strand never raises.** Eighty of them run at once, and one bad thread
ending the run would be the §8.1 failure mode with a new cause. Every
failure becomes a :class:`StrandOutcome` the orchestrator can account for,
and the corresponding §8.1 record is written where it happens. What a strand
must never do is disappear quietly: a run that read sixty of eighty
documents and says nothing about the twenty is exactly what §0.1 forbids.

**A strand counts, but never ranks.** One person, one vote holds across
documents, which no single strand can see. Analyses go to the accumulator,
and only the accumulator computes a ranking (§2.14.2).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from tripfinder.ai.errors import LLMProviderError
from tripfinder.analysis.comment_analysis import CommentAnalysis
from tripfinder.domain.models import (
    Comment,
    ResearchPlan,
    SourceDocument,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.health import SourceHealthRecorder
from tripfinder.pipeline.steps.comment_analysis import CommentAnalysisStep, batched
from tripfinder.pipeline.steps.prefilter import drop_reason
from tripfinder.pipeline.steps.retrieval import fetch_comments
from tripfinder.pipeline.streaming.accumulator import Accumulator
from tripfinder.pipeline.streaming.budget import CommentClass, RunBudget

logger = logging.getLogger(__name__)

STRAND_STEP_NAME = "strand"
"""What a strand's suppressions are recorded under in §8.1's accounting."""


@dataclass(frozen=True)
class StrandOutcome:
    """What one document contributed, and what it cost.

    ``failure`` is a named cause, never a bare truth value: a strand that
    lost its source and one that lost its model are different findings with
    different fixes (§8.1).
    """

    document_id: str
    comments_fetched: int = 0
    comments_admitted: int = 0
    comments_analysed: int = 0
    batches_attempted: int = 0
    batches_failed: int = 0
    failure: str | None = None


def _best(comments: Sequence[Comment], cap: int) -> list[Comment]:
    """The ``cap`` highest-scoring comments this document holds.

    The cap is what turns a bigger budget into a broader corpus rather than
    a deeper one. §2.12.3's finding 1 measured the alternative: comments were
    taken in document order until the budget ran out, so twelve threads
    supplied a run's entire evidence and sixty-six were never opened.

    Comments whose source reported no score keep the order the adapter left
    them in — unknown is not zero, but it has to sort somewhere, and "as
    fetched" invents no ranking of its own.
    """
    if cap <= 0 or len(comments) <= cap:
        return list(comments)
    ordered = sorted(comments, key=lambda comment: -(comment.score or 0))
    return ordered[:cap]


async def run_strand(
    context: PipelineContext,
    document: SourceDocument,
    *,
    comment_class: CommentClass,
    budget: RunBudget,
    accumulator: Accumulator,
    analyser: CommentAnalysisStep,
    recorder: SourceHealthRecorder,
    plan: ResearchPlan,
    comments_per_document: int,
    batch_size: int,
) -> StrandOutcome:
    """Carry one document from its address to counted opinions."""
    try:
        fetched = await fetch_comments(
            context, document, recorder=recorder, step_name=STRAND_STEP_NAME
        )
        if fetched is None:
            # Already recorded as a source failure by ``fetch_comments``.
            return StrandOutcome(document.id, failure="source_fetch_failed")

        capped = _best(fetched, comments_per_document)
        if len(capped) < len(fetched):
            context.research.diagnostics.record_suppression(
                step=STRAND_STEP_NAME,
                reason=SuppressionReason.BUDGET_MAX_COMMENTS,
                count=len(fetched) - len(capped),
                detail=f"comments beyond this document's cap of {comments_per_document}",
            )

        substantive = _prefilter(context, capped)
        granted = budget.reserve_comments(len(substantive), comment_class=comment_class)
        admitted = substantive[:granted]
        if not admitted:
            return StrandOutcome(document.id, comments_fetched=len(fetched))

        accumulator.register(admitted, comment_class=comment_class)
        analysed, attempted, failed = await _analyse(
            context,
            admitted,
            budget=budget,
            accumulator=accumulator,
            analyser=analyser,
            recorder=recorder,
            plan=plan,
            batch_size=batch_size,
        )
        return StrandOutcome(
            document_id=document.id,
            comments_fetched=len(fetched),
            comments_admitted=len(admitted),
            comments_analysed=analysed,
            batches_attempted=attempted,
            batches_failed=failed,
        )
    except Exception as exc:  # one document must never end a run
        logger.warning("strand %s failed: %s", document.id, exc)
        return StrandOutcome(document.id, failure=type(exc).__name__)


def _prefilter(context: PipelineContext, comments: Sequence[Comment]) -> list[Comment]:
    """Substance only, never topic — plan §4.6 step 6's rule, unchanged."""
    config = context.research.research_config.prefilter
    kept: list[Comment] = []
    for comment in comments:
        reason = drop_reason(comment, config)
        if reason is None:
            kept.append(comment)
        else:
            context.research.diagnostics.record_suppression(
                step=STRAND_STEP_NAME, reason=reason, count=1
            )
    return kept


async def _analyse(
    context: PipelineContext,
    comments: Sequence[Comment],
    *,
    budget: RunBudget,
    accumulator: Accumulator,
    analyser: CommentAnalysisStep,
    recorder: SourceHealthRecorder,
    plan: ResearchPlan,
    batch_size: int,
) -> tuple[int, int, int]:
    """Analyse this document's share, one admitted batch at a time."""
    analysed = attempted = failed = 0
    for batch in batched(comments, batch_size):
        if not budget.admit_analysis_batch(len(batch)):
            # Budget or deadline. Both are already tallied on the budget,
            # and neither is this strand's failure.
            break
        attempted += 1
        # The only queue in the system, because this is where the money and
        # the provider's rate limit are (§2.14.2).
        async with budget.call_slots:
            result = await _one_call(context, analyser, plan, batch, recorder=recorder)
        if result is None:
            failed += 1
            continue
        analysed += len(result)
        if result:
            await accumulator.batch_finished(result)
    return analysed, attempted, failed


async def _one_call(
    context: PipelineContext,
    analyser: CommentAnalysisStep,
    plan: ResearchPlan,
    batch: Sequence[Comment],
    *,
    recorder: SourceHealthRecorder,
) -> dict[str, CommentAnalysis] | None:
    """One analysis call. ``None`` means it failed and was recorded (§8.1)."""
    adapter = "llm:comment_analysis"
    try:
        result = await analyser.analyse_batch(context, plan, batch)
    except LLMProviderError as exc:
        logger.warning("strand analysis batch failed: %s", exc)
        context.research.diagnostics.record_suppression(
            step=STRAND_STEP_NAME,
            reason=SuppressionReason.ANALYSIS_BATCH_FAILED,
            count=len(batch),
            detail=type(exc).__name__,
        )
        recorder.record_failure(adapter, kind=type(exc).__name__)
        return None
    recorder.record_success(adapter)
    context.research.diagnostics.quote_verifications.extend(result.audit)
    return result.analyses
