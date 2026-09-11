"""Comment Analysis (plan §4.6 step 7, §5).

The one AI pass over comment text. It reads what triage kept and pre-filter
let through, and produces a :class:`CommentAnalysis` per comment: how
relevant it is, what it names, and how warmly.

Two deterministic guards wrap the model's answer.

**Quote verification** (`PROJECT.md` §29, plan §5, §2.12.1). Every
``supporting_quote`` must be findable in the stored comment body — exactly,
or after normalising both sides and matching at the configured similarity
threshold. A mention whose quote is not is discarded and counted, and every
non-exact decision is written to the audit trail either way. This is a
check, not a prompt instruction: a prompt asks the model not to invent
evidence, and this makes invented evidence unusable when it asks in vain.

**Nothing is assumed answered.** An item naming a comment we did not send is
dropped, and a comment the model skipped is recorded as suppressed — not
quietly treated as a comment with nothing to say. That distinction is plan
§0.1's whole subject: a comment with no analysis and a comment analysed as
irrelevant produce the same empty contribution to the ranking, and only one
of them is a finding.

**Provisional results** (plan §2.13). This is also the step a run spends
most of its time in, so it is where the waiting happens — and each batch
that comes back is a moment where a new ranking is worth showing. Every
batch with analyses in it hands them to a snapshot emitter, which ranks
everything analysed so far and passes it to the context's listener. None of
that touches the run's own record: the merge below still happens in batch
order, a snapshot is display state, and §2.13.2 forbids deriving a
statistic, a suppression or a status from one.

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
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import NamedTuple

from tripfinder.ai.errors import LLMCredentialError, LLMProviderError
from tripfinder.analysis.comment_analysis import (
    CommentAnalysis,
    CommentAnalysisBatch,
    EntityMention,
    build_comment_analysis_prompt,
)
from tripfinder.analysis.quote_verification import verify_quote
from tripfinder.domain.models import (
    Comment,
    QuoteVerdict,
    QuoteVerification,
    ReasonCode,
    ResearchFlag,
    ResearchPlan,
    SuppressionReason,
)
from tripfinder.pipeline.base import PartialResults, PipelineContext
from tripfinder.pipeline.deadline import admission_deadline
from tripfinder.pipeline.health import get_recorder, reassess_after_analysis
from tripfinder.pipeline.snapshot import snapshot
from tripfinder.sources.failures import failure_kind

logger = logging.getLogger(__name__)

DEFAULT_ANALYSIS_BATCH_SIZE = 20
"""Comments per structured call (plan §5)."""

ANALYSIS_ADAPTER = "llm:comment_analysis"
"""The name analysis batches are accounted under in §8.1's health table.

§8.1 says the LLM is accounted "the same way" as a source, and the outcome
rules are already written for N adapters — so the analysis call is simply
another adapter in the same recorder, rather than a parallel accounting
scheme with its own rules to keep in step.
"""

DEFAULT_MAX_CONCURRENT_BATCHES = 16
"""Batches in flight at once (plan §2.12, 14.6b).

Derived, not guessed. A 20-comment batch measured 23.2 s at
``reasoning.effort=low``, and ``maxAIAnalysisItems`` of 1000 is 50 batches:
sequentially 1160 s, against an admission window of 240 s once §2.12.2's
tail reserve comes off the 300 s budget. Fitting 50 batches into that window
needs about five in flight; eight leaves headroom for batches slower than
the measured one without pushing hard into provider rate limits, which
answer with 429s that §8.1 has to account for as lost evidence.

Raised to 16 for 14.8 (plan §2.14.1). The arithmetic that sets it changed:
a top result of 100 supporters needs ~1500 analysed comments, which is 75
calls, and per-call latency does not shrink when the payload does (§2.12.3).
Waves are therefore the only variable left. 16 is a deliberate half-step —
§2.14.1's arithmetic asks for ~80, and this is the value being tried first
against a real account's rate limit before going wider.

Phase 15 tunes this against real runs. It is the kind of number that should
move once there is more than one measurement behind it.
"""


class _SnapshotEmitter:
    """Turns each finished batch into a provisional ranking (plan §2.13).

    Two guards, and the plan calls both of them required.

    **Single-flight with coalescing.** The first wave of batches finishes
    within a second or two of itself. One snapshot computation and one
    persistence write per batch would have eight of them racing; instead a
    computation already in progress marks the state dirty and the emitter
    recomputes once when it is done. That also sets the update rhythm —
    roughly one snapshot per wave — with no timer to tune.

    **A sequence number.** ``batches_completed`` counts the batches a
    snapshot actually covers, so a listener can refuse anything that does
    not advance it. Without that, a snapshot covering three batches could
    land after one covering five and the counts on screen would go *down*,
    breaking the one promise (§2.13.1) that makes a provisional answer safe
    to show at all.

    Failed and undispatched batches emit nothing: they add no analyses, so
    the snapshot would be identical to the last one, and at the deadline
    every remaining batch returns at once.
    """

    def __init__(
        self,
        context: PipelineContext,
        *,
        counted: Sequence[Comment],
        evidence: Sequence[Comment],
    ) -> None:
        self._context = context
        self._counted = list(counted)
        self._evidence = list(evidence)
        self._analyses: dict[str, CommentAnalysis] = {}
        self._batches = 0
        self._computing = False
        self._dirty = False

    async def batch_finished(self, analyses: Mapping[str, CommentAnalysis]) -> None:
        """Accumulate one batch's analyses, and emit a snapshot of everything so far."""
        listener = self._context.on_partial_results
        if listener is None:
            return

        # Every snapshot is cumulative — everything finished so far, never
        # just the batch that has only now come back.
        self._analyses.update(analyses)
        self._batches += 1

        if self._computing:
            self._dirty = True
            return
        self._computing = True
        try:
            while True:
                self._dirty = False
                await self._emit()
                if not self._dirty:
                    return
        finally:
            self._computing = False

    async def _emit(self) -> None:
        listener = self._context.on_partial_results
        if listener is None:
            return
        # Read the accumulator once, before the first await: what this
        # snapshot covers must not change underneath it.
        counted = _in_order(self._counted, self._analyses)
        evidence = _in_order(self._evidence, self._analyses)
        batches = self._batches

        results, weak_results = await snapshot(
            self._context, counted_analyses=counted, evidence_analyses=evidence
        )
        await listener(
            PartialResults(
                results=results,
                weak_results=weak_results,
                batches_completed=batches,
                comments_analysed=len(counted) + len(evidence),
            )
        )


class _BatchResult(NamedTuple):
    """What one structured call produced, and what it cost in dropped evidence."""

    analyses: dict[str, CommentAnalysis]
    discarded: int
    """Items that named no comment in the batch, or named one twice."""

    fabricated: int
    """Mentions whose supporting quote was not in the comment."""

    unanswered: tuple[str, ...]
    """Comments this batch asked about and got no verdict for."""

    lost: tuple[str, ...]
    """Comments whose whole batch failed. Empty unless ``failure`` is set."""

    undispatched: tuple[str, ...] = ()
    """Comments in a batch the deadline refused to admit. Budget-limited, not failed."""

    audit: tuple[QuoteVerification, ...] | list[QuoteVerification] = ()
    """Every non-exact quote decision this batch made (plan §2.12.1)."""

    failure: str | None = None
    """The §8.1 failure kind, when this batch raised instead of answering."""


def batched(comments: Sequence[Comment], size: int) -> Iterator[Sequence[Comment]]:
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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._batch_size = batch_size
        self._max_concurrent_batches = max_concurrent_batches
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(self, context: PipelineContext) -> PipelineContext:
        plan: ResearchPlan = context.data["plan"]
        counted: list[Comment] = list(context.data.get("counted_comments", []))
        evidence: list[Comment] = list(context.data.get("evidence_comments", []))

        # Counted comments first, in the §4.5 budget order pre-filter left
        # them in: the corpus that decides the ranking is dispatched before
        # the corpus that only illustrates it.
        batches = list(batched(counted + evidence, self._batch_size))
        emitter = _SnapshotEmitter(context, counted=counted, evidence=evidence)
        results = await self._analyse_all(context, plan, batches, emitter)

        # Merged in batch order, never in completion order. Concurrency is
        # about when a call is *made*; two runs over the same corpus still
        # have to produce the same statistics and the same suppressions.
        analyses: dict[str, CommentAnalysis] = {}
        discarded = 0
        fabricated = 0
        unanswered: list[str] = []
        lost: list[str] = []
        undispatched: list[str] = []
        failures: Counter[str] = Counter()
        for result in results:
            analyses.update(result.analyses)
            discarded += result.discarded
            fabricated += result.fabricated
            unanswered.extend(result.unanswered)
            lost.extend(result.lost)
            undispatched.extend(result.undispatched)
            context.research.diagnostics.quote_verifications.extend(result.audit)
            if result.failure is not None:
                failures[result.failure] += 1
        self._record_suppressions(context, fabricated, unanswered, lost, undispatched, failures)

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
        statistics["analysis_batches_attempted"] = len(batches)
        statistics["analysis_batches_failed"] = sum(failures.values())
        statistics["comments_lost_to_errors"] = len(lost)
        statistics["comments_not_analysed_budget"] = len(undispatched)
        statistics["analysis_batches_not_dispatched"] = sum(
            1 for result in results if result.undispatched
        )

        # §8.1: the gap between what was sent and what came back is accounted
        # here, by the step that caused it, rather than left for a later step
        # to infer from statistics it did not produce.
        reassess_after_analysis(context, comments_analyzed=len(analyses))
        statistics.update(_reason_code_counts(analyses.values()))
        return context

    async def _analyse_all(
        self,
        context: PipelineContext,
        plan: ResearchPlan,
        batches: Sequence[Sequence[Comment]],
        emitter: _SnapshotEmitter,
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
        recorder = get_recorder(context)
        deadline = admission_deadline(context)

        async def dispatch_one(index: int, batch: Sequence[Comment]) -> _BatchResult:
            async with limit:
                # The clock is read here, holding the semaphore, because this
                # is the moment of dispatch — checking it up front would
                # admit a batch that only goes out minutes later (§2.12.2).
                #
                # The first wave is exempt. A run that paid for query
                # understanding, triage and retrieval and then analysed
                # nothing is the worst outcome available: full cost, no
                # evidence, and a results page that cannot say anything. One
                # wave costs one batch latency.
                if index >= self._max_concurrent_batches and self._clock() > deadline:
                    return _BatchResult(
                        analyses={},
                        discarded=0,
                        fabricated=0,
                        unanswered=(),
                        lost=(),
                        undispatched=tuple(comment.id for comment in batch),
                    )
                try:
                    result = await self.analyse_batch(context, plan, batch)
                except LLMCredentialError:
                    # Not a property of this batch. A run with no credential
                    # cannot analyse anything, so isolating it would turn a
                    # configuration error into a quiet degradation — exactly
                    # the masquerade §0.1 forbids. It stays fatal.
                    raise
                except LLMProviderError as exc:
                    recorder.record_failure(ANALYSIS_ADAPTER, kind=failure_kind(exc))
                    logger.warning(
                        "analysis: a batch of %d comment(s) failed (%s): %s",
                        len(batch),
                        exc.kind.value,
                        exc,
                    )
                    return _BatchResult(
                        analyses={},
                        discarded=0,
                        fabricated=0,
                        unanswered=(),
                        lost=tuple(comment.id for comment in batch),
                        failure=exc.kind.value,
                    )
                recorder.record_success(ANALYSIS_ADAPTER)
                return result

        async def analyse_one(index: int, batch: Sequence[Comment]) -> _BatchResult:
            result = await dispatch_one(index, batch)
            # Outside the semaphore, deliberately: a snapshot is cheap, but
            # it is not a model call, and holding a dispatch slot while one
            # is computed would make the run slower to buy nothing.
            if result.analyses:
                await emitter.batch_finished(result.analyses)
            return result

        return list(
            await asyncio.gather(
                *(analyse_one(index, batch) for index, batch in enumerate(batches))
            )
        )

    async def analyse_batch(
        self, context: PipelineContext, plan: ResearchPlan, batch: Sequence[Comment]
    ) -> _BatchResult:
        """One structured call, matched back to the comments it was asked about.

        Public because 14.8's strands issue exactly this call (plan §2.14.2).
        The step keeps owning it: quote verification, the discard rules and
        the audit trail are the analysis contract (§5), and a strand that
        re-implemented any of them would be a second contract.
        """
        response = await context.llm.complete_structured(
            prompt=build_comment_analysis_prompt(plan, batch),
            response_model=CommentAnalysisBatch,
        )
        requested = {comment.id: comment for comment in batch}

        analyses: dict[str, CommentAnalysis] = {}
        discarded = 0
        fabricated = 0
        audit: list[QuoteVerification] = []
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
            analysis, rejected, records = self._verify_quotes(context, item, comment)
            analyses[item.comment_id] = analysis
            fabricated += rejected
            audit.extend(records)

        unanswered = tuple(
            comment_id for comment_id in requested if comment_id not in analyses
        )
        return _BatchResult(analyses, discarded, fabricated, unanswered, lost=(), audit=audit)

    def _verify_quotes(
        self, context: PipelineContext, item: CommentAnalysis, comment: Comment
    ) -> tuple[CommentAnalysis, int, list[QuoteVerification]]:
        """Keep only the mentions whose quote is really findable in the comment.

        Returns the audit records rather than writing them, so that batches
        running concurrently cannot interleave them (14.6b): the caller
        appends in batch order.
        """
        threshold = context.research.research_config.quote_verification.similarity_threshold
        verified: list[EntityMention] = []
        audit: list[QuoteVerification] = []

        for mention in item.mentions:
            match = verify_quote(mention.supporting_quote, comment.body)
            accepted = match.similarity >= threshold
            if accepted:
                verified.append(mention)
            else:
                logger.warning(
                    "analysis: discarding a mention of %r in comment %s — "
                    "its supporting quote matches the body at only %.2f",
                    mention.raw_text,
                    comment.id,
                    match.similarity,
                )
            if not match.exact:
                # Exact substrings are the uninteresting case and there are
                # thousands of them. What the threshold needs revisiting
                # against is the borderline — both sides of it (§2.12.1).
                audit.append(
                    QuoteVerification(
                        comment_id=comment.id,
                        mention_text=mention.raw_text,
                        claimed_quote=mention.supporting_quote,
                        matched_span=match.matched_span,
                        similarity=match.similarity,
                        verdict=QuoteVerdict.ACCEPTED if accepted else QuoteVerdict.REJECTED,
                    )
                )

        rejected = len(item.mentions) - len(verified)
        if rejected == 0:
            return item, 0, audit
        return item.model_copy(update={"mentions": verified}), rejected, audit

    def _record_suppressions(
        self,
        context: PipelineContext,
        fabricated: int,
        unanswered: Sequence[str],
        lost: Sequence[str],
        undispatched: Sequence[str],
        failures: Counter[str],
    ) -> None:
        """Once, after every batch is in — so the record does not depend on timing."""
        diagnostics = context.research.diagnostics
        if undispatched:
            # Budget-limited, not failed, and the two are different claims:
            # this one says "we stopped on purpose, the sample is valid and
            # smaller"; ANALYSIS_BATCH_FAILED says "we tried and could not
            # see" (§0.1, §7.1's completed_partial vs completed_degraded).
            budget = context.research.research_config.budget
            diagnostics.record_suppression(
                step=self.name,
                reason=SuppressionReason.BUDGET_MAX_RESEARCH_DURATION,
                count=len(undispatched),
                detail=(
                    "comments never sent for analysis — the dispatch deadline "
                    f"({budget.max_research_duration_seconds}s budget minus a "
                    f"{budget.tail_reserve_seconds}s tail reserve) had passed"
                ),
            )
            diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)
            logger.info(
                "analysis: %d comment(s) not dispatched — past the admission deadline",
                len(undispatched),
            )
        if lost:
            kinds = ", ".join(f"{kind} x{count}" for kind, count in sorted(failures.items()))
            diagnostics.record_suppression(
                step=self.name,
                reason=SuppressionReason.ANALYSIS_BATCH_FAILED,
                count=len(lost),
                detail=f"comments in batches that failed outright ({kinds})",
            )
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
