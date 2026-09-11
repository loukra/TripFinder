"""Discovery, triage and strands, all at once (plan §2.14.2).

What this replaces is not the work but the *waiting*. §4.6 steps 3-7 ran as
a list: find every document, then classify every document, then fetch every
document, then analyse. §2.12.3 measured the cost — discovery alone was
56.6 s of a 282.5 s run, fully sequential, and no downstream step could start
until all of it had finished. Roughly 135 s of a five-minute run was spent
before the first analysis call went out.

Documents are independent, so none of that ordering was a data dependency.
Here discovery **produces** into a queue while a consumer triages each wave
and starts a strand per surviving document. A thread found by the first
search is being read while the model is still proposing the fourth.

Three things remain run-wide, and each is an object rather than a step
boundary: the purse (:class:`RunBudget`), the denominator
(:class:`Accumulator`) and §8.1's floor (:class:`HealthGate`).

Steps 8-11 are untouched. They run once, at the end, over everything the
accumulator holds — which is the same code path 14.7's snapshots take
(§2.13.2), so the final answer and the provisional ones are computed by one
implementation of the metric.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from tripfinder.domain.models import (
    ResearchFlag,
    ResearchPlan,
    ResearchStatus,
    SourceDocument,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.deadline import admission_deadline
from tripfinder.pipeline.health import get_recorder, reassess_after_analysis
from tripfinder.pipeline.steps.comment_analysis import (
    DEFAULT_ANALYSIS_BATCH_SIZE,
    DEFAULT_MAX_CONCURRENT_BATCHES,
    CommentAnalysisStep,
    _reason_code_counts,
)
from tripfinder.pipeline.steps.discovery import discover_documents
from tripfinder.pipeline.steps.triage import DocumentTriageStep, record_triage_totals
from tripfinder.pipeline.streaming.accumulator import Accumulator
from tripfinder.pipeline.streaming.budget import CommentClass, RunBudget
from tripfinder.pipeline.streaming.gate import HealthGate
from tripfinder.pipeline.streaming.strand import StrandOutcome, run_strand

logger = logging.getLogger(__name__)

_QUEUE_END = None


async def run_strands(
    context: PipelineContext,
    *,
    batch_size: int = DEFAULT_ANALYSIS_BATCH_SIZE,
    max_concurrent_calls: int = DEFAULT_MAX_CONCURRENT_BATCHES,
) -> list[StrandOutcome]:
    """Search, triage, fetch and analyse, all overlapping. Returns each
    strand's outcome, in the order the documents were discovered."""
    plan: ResearchPlan = context.data["plan"]
    config = context.research.research_config
    recorder = get_recorder(context)

    budget = RunBudget(
        max_comments=config.budget.max_comments,
        max_analysis_items=config.budget.max_ai_analysis_items,
        max_concurrent_calls=max_concurrent_calls,
        topical_quota=config.budget.topical_quota,
        deadline=admission_deadline(context),
    )
    accumulator = Accumulator(context)
    gate = HealthGate(minimum_documents=config.source_health_floors.min_posts_retrieved)
    triage = DocumentTriageStep()
    analyser = CommentAnalysisStep(batch_size=batch_size)

    queue: asyncio.Queue[Sequence[SourceDocument] | None] = asyncio.Queue()
    strands: list[asyncio.Task[StrandOutcome]] = []
    polling: list[SourceDocument] = []
    topical: list[SourceDocument] = []
    triaged = 0
    # §4.5: topical material spends what polling leaves. With no share set
    # aside for it there is nothing to spend, so those documents are never
    # opened — which is the point, since the fetch is the first cost and it
    # is paid before anything can be refused.
    opens_topical = budget.has_allowance(CommentClass.EVIDENCE)

    async def produce() -> None:
        """Search, and hand each turn's documents on without waiting."""
        try:
            async for wave in discover_documents(context):
                await queue.put(wave)
        finally:
            await queue.put(_QUEUE_END)

    async def consume() -> None:
        """Triage each wave and start a strand per surviving document."""
        nonlocal triaged
        while True:
            wave = await queue.get()
            if wave is _QUEUE_END:
                return
            assert wave is not None
            admitted = _within_post_budget(context, wave, already=triaged)
            if not admitted:
                continue
            context.research.status = ResearchStatus.ANALYZING
            decisions = await triage.classify(context, admitted)
            wave_polling, wave_topical = triage.apply_decisions(context, admitted, decisions)
            triaged += len(admitted)
            polling.extend(wave_polling)
            topical.extend(wave_topical)

            for document, comment_class in (
                *((document, CommentClass.COUNTED) for document in wave_polling),
                *(
                    (document, CommentClass.EVIDENCE)
                    for document in (wave_topical if opens_topical else ())
                ),
            ):
                strands.append(
                    asyncio.create_task(
                        run_strand(
                            context,
                            document,
                            comment_class=comment_class,
                            budget=budget,
                            accumulator=accumulator,
                            analyser=analyser,
                            recorder=recorder,
                            plan=plan,
                            comments_per_document=config.budget.max_comments_per_document,
                            batch_size=batch_size,
                            gate=gate,
                        )
                    )
                )

    context.research.status = ResearchStatus.DISCOVERING
    await asyncio.gather(produce(), consume())
    # Discovery cannot produce another document, so a run that never reached
    # §8.1's floor stops waiting for one and goes on to fail honestly.
    gate.discovery_finished()
    outcomes = await asyncio.gather(*strands)

    if topical and not opens_topical:
        # §0.1: a document nobody opened is a suppression, not an absence.
        # Triage already said *why* each one is topical; this says what
        # happened to it as a result.
        context.research.diagnostics.record_suppression(
            step="document_triage",
            reason=SuppressionReason.TOPICAL_UNOPENED,
            count=len(topical),
            detail=(
                "topical documents were classified but never fetched — §4.5 gives them only "
                "the budget polling leaves, and topicalQuota reserves none"
            ),
        )

    record_triage_totals(
        context,
        triaged=triaged,
        polling=polling,
        topical=topical,
        floors=config.triage_floors,
    )
    _publish(context, accumulator, budget, outcomes)
    reassess_after_analysis(context, comments_analyzed=len(accumulator.corpus()[0]))
    return list(outcomes)


def _within_post_budget(
    context: PipelineContext, wave: Sequence[SourceDocument], *, already: int
) -> list[SourceDocument]:
    """``maxTotalPosts``, applied across waves rather than to one list.

    Triage costs a model call per batch, so the cap has to bite before the
    classification rather than after it — the same reason the sequential step
    applied it first.
    """
    cap = context.research.research_config.budget.max_total_posts
    room = cap - already
    if room >= len(wave):
        return list(wave)
    if room <= 0:
        refused = len(wave)
    else:
        refused = len(wave) - room
    context.research.diagnostics.record_suppression(
        step="document_triage",
        reason=SuppressionReason.BUDGET_MAX_TOTAL_POSTS,
        count=refused,
        detail=f"documents beyond the {cap}-post budget",
    )
    context.research.diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)
    return list(wave[:room]) if room > 0 else []


def _publish(
    context: PipelineContext,
    accumulator: Accumulator,
    budget: RunBudget,
    outcomes: Sequence[StrandOutcome],
) -> None:
    """Hand steps 8-11 exactly what the sequential steps used to hand them."""
    counted, evidence = accumulator.corpus()
    # §8.1's assessment reads this key, and §4.5's split is already made:
    # `comments` holds exactly what strands admitted.
    context.data["analysis_comments"] = list(context.data.get("comments", []))
    context.data["counted_analyses"] = counted
    context.data["evidence_analyses"] = evidence
    context.data["comment_analyses"] = counted + evidence

    retrieved = sum(1 for outcome in outcomes if outcome.failure != "source_fetch_failed")
    fetched = sum(outcome.comments_fetched for outcome in outcomes)
    admitted = sum(outcome.comments_admitted for outcome in outcomes)

    statistics = context.research.statistics
    statistics["documents_retrieved"] = retrieved
    statistics["posts_retrieved"] = retrieved
    statistics["comments_retrieved"] = fetched
    statistics["comments_counted_corpus"] = budget.comments_spent(CommentClass.COUNTED)
    statistics["comments_evidence_corpus"] = budget.comments_spent(CommentClass.EVIDENCE)
    statistics["comments_analyzed"] = admitted
    statistics["comments_with_analysis"] = len(counted) + len(evidence)
    statistics["comments_without_analysis"] = admitted - len(counted) - len(evidence)
    statistics["analysis_batches_attempted"] = sum(
        outcome.batches_attempted for outcome in outcomes
    )
    statistics["analysis_batches_failed"] = sum(outcome.batches_failed for outcome in outcomes)
    statistics["strands_failed"] = sum(1 for outcome in outcomes if outcome.failure)
    statistics["analysis_mentions_extracted"] = sum(
        len(analysis.mentions) for analysis in [*counted, *evidence]
    )
    statistics["analysis_mentions_fabricated_quote"] = _total(outcomes, "mentions_fabricated")
    statistics["analysis_items_discarded"] = _total(outcomes, "items_discarded")
    statistics.update(_reason_code_counts([*counted, *evidence]))
    context.data["posts_retrieved"] = retrieved

    # Every §5 discard, recorded by the phase that caused it rather than
    # left for a later step to infer from a shorter list (plan §0.1).
    _record(
        context,
        SuppressionReason.ANALYSIS_FABRICATED_QUOTE,
        _total(outcomes, "mentions_fabricated"),
        "mentions whose supporting quote was not findable in the comment",
    )
    _record(
        context,
        SuppressionReason.ANALYSIS_NO_RESULT,
        _total(outcomes, "comments_unanswered"),
        "comments sent for analysis that came back without one",
    )

    # Comments a strand was never granted. Tallied by the purse, and
    # surfaced here — a corpus that shrank because the budget said no has to
    # be distinguishable from one that was genuinely small (§0.1).
    for comment_class, refused in budget.comments_refused.items():
        _record(
            context,
            SuppressionReason.BUDGET_MAX_COMMENTS,
            refused,
            f"{comment_class.value} comments beyond that corpus's share of the budget",
        )
    if budget.comments_refused[CommentClass.COUNTED] or budget.comments_refused[
        CommentClass.EVIDENCE
    ]:
        context.research.diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)

    if budget.items_refused_for_deadline:
        context.research.diagnostics.record_suppression(
            step="strand",
            reason=SuppressionReason.BUDGET_MAX_AI_ANALYSIS_ITEMS,
            count=budget.items_refused_for_deadline,
            detail="comments never sent for analysis — the dispatch deadline had passed",
        )
        context.research.diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)
    if budget.items_refused_for_budget:
        context.research.diagnostics.record_suppression(
            step="strand",
            reason=SuppressionReason.BUDGET_MAX_AI_ANALYSIS_ITEMS,
            count=budget.items_refused_for_budget,
            detail="comments beyond the analysis budget",
        )
        context.research.diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)


def _total(outcomes: Sequence[StrandOutcome], field: str) -> int:
    return sum(getattr(outcome, field) for outcome in outcomes)


def _record(
    context: PipelineContext, reason: SuppressionReason, count: int, detail: str
) -> None:
    if count:
        context.research.diagnostics.record_suppression(
            step="strand", reason=reason, count=count, detail=detail
        )


class StreamingStrandsStep:
    """§4.6 steps 3-7, run as one concurrent phase (plan §2.14.2).

    A step so that the runner's progress reporting, cancellation checks and
    LLM-failure handling apply to it exactly as they did to the five steps it
    replaces. What it is *not* is a fifth ordering: inside it, discovery,
    triage, retrieval, pre-filtering and analysis all overlap.
    """

    name = "parallel_strands"

    def __init__(
        self,
        *,
        batch_size: int = DEFAULT_ANALYSIS_BATCH_SIZE,
        max_concurrent_calls: int = DEFAULT_MAX_CONCURRENT_BATCHES,
    ) -> None:
        self._batch_size = batch_size
        self._max_concurrent_calls = max_concurrent_calls

    async def run(self, context: PipelineContext) -> PipelineContext:
        await run_strands(
            context,
            batch_size=self._batch_size,
            max_concurrent_calls=self._max_concurrent_calls,
        )
        return context
