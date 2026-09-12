"""The run's shared denominator (plan §2.14.2).

One person, one vote holds across the whole run, so a strand may *count*
locally but nothing may be *ranked* locally: the same user can appear in two
documents, and only a global union can see that. This is that union.

It is deliberately thin, because the merge already exists. Plan §2.13.2
binds a snapshot to be the run's own steps 8-11 over a partial corpus and
never a second implementation of the metric, so this class accumulates
analyses and calls :func:`~tripfinder.pipeline.snapshot.snapshot` — the same
function 14.7 built, unchanged.

**Arrival order is not corpus order.** Strands finish in an order that
depends on network latency, so the accumulator sorts its material by
``(source_document_id, comment_id)`` before every snapshot. Two runs over the
same corpus therefore produce the same statistics and the same suppressions
whatever order the documents came back in — the guarantee
``CommentAnalysisStep`` gets for free by merging in batch order, and which a
concurrent pipeline has to restate explicitly.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence

from tripfinder.analysis.comment_analysis import CommentAnalysis
from tripfinder.domain.models import Comment
from tripfinder.pipeline.base import PartialResults, PipelineContext
from tripfinder.pipeline.snapshot import snapshot
from tripfinder.pipeline.steps.entity_resolution import EntityResolutionStep
from tripfinder.pipeline.streaming.budget import CommentClass
from tripfinder.pipeline.streaming.resolution import ResolutionCache

logger = logging.getLogger(__name__)


class Accumulator:
    """Everything analysed so far, and the snapshots computed from it.

    The single-flight guard and the sequence number are 14.7's, for 14.7's
    reasons (§2.13.2): a computation already running marks the state dirty
    and recomputes once when it finishes, and every snapshot says how many
    batches it covers so a listener can refuse one that does not advance.
    Under 14.8 they matter more, not less — eighty strands finishing at once
    would otherwise mean eighty snapshot computations racing each other.
    """

    def __init__(self, context: PipelineContext) -> None:
        self._context = context
        self._comments: dict[str, tuple[CommentClass, Comment]] = {}
        self._analyses: dict[str, CommentAnalysis] = {}
        self._batches = 0
        self._computing = False
        self._dirty = False
        self._priming: asyncio.Task[int] | None = None
        self._resolver = EntityResolutionStep()
        context.data.setdefault("resolution_cache", ResolutionCache())

    def register(self, comments: Sequence[Comment], *, comment_class: CommentClass) -> None:
        """Record which corpus these comments belong to, before they are analysed.

        Kept separate from :meth:`batch_finished` because §4.5's split is a
        property of the *document*, which the strand knows, while an
        analysis only knows a comment id.

        ``context.data["comments"]`` is republished as a **fresh list** each
        time rather than appended to. Deduplication resolves a comment id
        back to its author through that key, and ``snapshot`` shallow-copies
        ``data`` — so a shared list would let a strand append to the very
        list a snapshot is walking.
        """
        for comment in comments:
            self._comments[comment.id] = (comment_class, comment)
        self._context.data["comments"] = [comment for _, comment in self._comments.values()]

    async def batch_finished(self, analyses: Mapping[str, CommentAnalysis]) -> None:
        """Add one call's analyses and emit a snapshot of everything so far.

        **Accumulating and emitting are separate.** Under 14.7 this class's
        ancestor could return early with no listener, because a snapshot
        nobody receives is wasted work. Under 14.8 this is also the run's
        corpus — steps 8-11 read what it holds — so skipping the
        accumulation would produce a run that analysed everything and
        reported nothing. A missing listener silences the snapshots and
        nothing else.
        """
        self._analyses.update(analyses)
        self._batches += 1
        self._prime()
        if self._context.on_partial_results is None:
            return

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

    def _prime(self) -> None:
        """Start placing the names this batch raised, if nothing is placing already.

        Resolution used to run once, after every analysis call had finished,
        which had two consequences and they were the same consequence: the
        run spent minutes in a sequential tail doing nothing else, and every
        snapshot until then ranked only what the catalogue could place by
        itself — nothing at all, for any question that is not about US
        states (``streaming/resolution.py``).

        Asking *while* analysis runs fixes both. It is fire-and-forget on
        purpose: a strand that has just finished a batch must not wait for a
        model call it does not need, and a snapshot taken meanwhile simply
        sees whichever names have landed. A failure here costs a snapshot
        some entities and nothing else — the final resolution step asks for
        whatever is still missing, exactly as it always did.
        """
        if self._priming is not None and not self._priming.done():
            return
        self._priming = asyncio.create_task(self._prime_once())

    async def _prime_once(self) -> int:
        counted, evidence = self.corpus()
        try:
            return await self._resolver.prime(
                self._context, counted_analyses=counted, evidence_analyses=evidence
            )
        except Exception:
            # A name the cache does not hold is a name the final resolution
            # step will ask about, so the worst this costs is a thinner
            # snapshot. It is never a reason to fail a run that is reading
            # perfectly well.
            logger.warning("resolution: priming the name cache failed", exc_info=True)
            return 0

    async def settle(self) -> None:
        """Wait for an in-flight priming call, so nothing outlives the run."""
        if self._priming is not None:
            await self._priming
            self._priming = None

    def corpus(self) -> tuple[list[CommentAnalysis], list[CommentAnalysis]]:
        """Everything analysed so far, in corpus order: counted, then evidence."""
        counted: list[CommentAnalysis] = []
        evidence: list[CommentAnalysis] = []
        for comment_id in sorted(
            self._analyses,
            key=lambda key: (
                self._comments[key][1].source_document_id if key in self._comments else "",
                key,
            ),
        ):
            known = self._comments.get(comment_id)
            if known is None:
                # An analysis for a comment no strand registered cannot be
                # attributed to either corpus, so it is not evidence for
                # either (plan §5 — dropped, never coerced).
                continue
            sink = counted if known[0] is CommentClass.COUNTED else evidence
            sink.append(self._analyses[comment_id])
        return counted, evidence

    async def _emit(self) -> None:
        listener = self._context.on_partial_results
        if listener is None:
            return
        # Read the accumulator once, before the first await: what this
        # snapshot covers must not change underneath it.
        counted, evidence = self.corpus()
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
