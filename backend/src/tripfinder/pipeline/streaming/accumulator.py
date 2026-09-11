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

from collections.abc import Mapping, Sequence

from tripfinder.analysis.comment_analysis import CommentAnalysis
from tripfinder.domain.models import Comment
from tripfinder.pipeline.base import PartialResults, PipelineContext
from tripfinder.pipeline.snapshot import snapshot
from tripfinder.pipeline.streaming.budget import CommentClass


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
        """Add one call's analyses and emit a snapshot of everything so far."""
        if self._context.on_partial_results is None:
            return
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
