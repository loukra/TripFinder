"""Source Document Triage (plan §4.6 step 4, §4.7).

Gates everything downstream. Runs on discovery metadata only — no comment
tree is fetched for a document this step excludes, which is the whole point
of its placement (plan §4.7).

Two halves, in plan order:

* **Deterministic pre-checks** short-circuit the AI call entirely
  (`PROJECT.md` §6.4): too few comments, too old, a leading title naming an
  entity, an interrogative title naming none.
* **AI classification** handles the remainder, batched.

Every AI verdict then passes through deterministic overrides, and they only
ever move one way. A document may be **downgraded** to ``topical``; it may
never be **promoted** to ``polling``. Excluding a good thread costs
evidence; admitting a biased one corrupts the ranking, and only the second
is invisible to the user (plan §4.7).

Because this step is a single point of failure for the whole corpus, every
verdict is persisted with its reason, the breakdown reaches
``research.statistics``, and a polling share below
``minPollingDocumentRatio`` raises a flag rather than quietly producing a
thin-looking result (plan §4.7 mitigations 1-3, §0.1).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

from tripfinder.analysis.aliases import AliasTable, StaticAliasTable
from tripfinder.analysis.triage import (
    DocumentTriage,
    DocumentTriageBatch,
    build_triage_prompt,
)
from tripfinder.domain.config import TriageFloors
from tripfinder.domain.models import (
    ContextType,
    ResearchFlag,
    ResearchPlan,
    ResearchStatus,
    SourceDocument,
    SuppressionReason,
    TriageDecidedBy,
    TriageDecision,
    TriageVerdict,
)
from tripfinder.pipeline.base import PipelineContext

DEFAULT_TRIAGE_BATCH_SIZE = 120

_INTERROGATIVE_OPENERS = frozenset(
    {"what", "which", "where", "how", "why", "who", "when"}
)
_WORD = re.compile(r"[a-z']+")

_SUPPRESSION_REASONS: dict[TriageVerdict, SuppressionReason] = {
    TriageVerdict.EXCLUDE: SuppressionReason.TRIAGE_EXCLUDED,
    TriageVerdict.TOPICAL: SuppressionReason.TRIAGE_NOT_POLLING,
}


def _is_interrogative(title: str) -> bool:
    if "?" in title:
        return True
    words = _WORD.findall(title.lower())
    return bool(words) and words[0] in _INTERROGATIVE_OPENERS


def _batched(
    documents: Sequence[SourceDocument], size: int
) -> Iterator[Sequence[SourceDocument]]:
    for start in range(0, len(documents), size):
        yield documents[start : start + size]


class DocumentTriageStep:
    """Real implementation of plan §4.6 step 4."""

    name = "document_triage"

    def __init__(
        self,
        aliases: AliasTable | None = None,
        *,
        batch_size: int = DEFAULT_TRIAGE_BATCH_SIZE,
        now: datetime | None = None,
    ) -> None:
        self._aliases = aliases if aliases is not None else StaticAliasTable()
        self._batch_size = batch_size
        self._now = now

    async def run(self, context: PipelineContext) -> PipelineContext:
        plan: ResearchPlan = context.data["plan"]
        floors = context.research.research_config.triage_floors
        now = self._now or datetime.now(UTC)

        documents = self._apply_post_budget(context)

        decisions: dict[str, TriageDecision] = {}
        undecided: list[SourceDocument] = []
        for document in documents:
            decision = self._pre_check(document, plan, floors, now=now)
            if decision is None:
                undecided.append(document)
            else:
                decisions[document.id] = decision

        for batch in _batched(undecided, self._batch_size):
            decisions.update(await self._classify(context, plan, batch, floors, now=now))

        self._apply(context, documents, decisions, floors)
        context.research.status = ResearchStatus.RETRIEVING
        return context

    def _apply_post_budget(self, context: PipelineContext) -> list[SourceDocument]:
        """Enforce ``maxTotalPosts`` here — before triage pays to classify them."""
        documents: list[SourceDocument] = list(context.data.get("documents", []))
        cap = context.research.research_config.budget.max_total_posts
        if len(documents) <= cap:
            return documents

        diagnostics = context.research.diagnostics
        diagnostics.record_suppression(
            step=self.name,
            reason=SuppressionReason.BUDGET_MAX_TOTAL_POSTS,
            count=len(documents) - cap,
        )
        diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)
        return documents[:cap]

    def _pre_check(
        self,
        document: SourceDocument,
        plan: ResearchPlan,
        floors: TriageFloors,
        *,
        now: datetime,
    ) -> TriageDecision | None:
        """The deterministic checks, cheapest first. ``None`` means "ask the model"."""
        if document.comment_count < floors.min_comments_per_document:
            return TriageDecision(
                document_id=document.id,
                verdict=TriageVerdict.EXCLUDE,
                reason=(
                    f"only {document.comment_count} comments, below the floor of "
                    f"{floors.min_comments_per_document}"
                ),
                confidence=1.0,
                decided_by=TriageDecidedBy.RULE,
            )

        age_years = (now - document.created_at).days / 365.25
        if age_years > floors.max_document_age_years:
            return TriageDecision(
                document_id=document.id,
                verdict=TriageVerdict.EXCLUDE,
                reason=(
                    f"posted {age_years:.0f} years ago, beyond the "
                    f"{floors.max_document_age_years}-year limit"
                ),
                confidence=1.0,
                decided_by=TriageDecidedBy.RULE,
            )

        # A table with no aliases at this tier cannot tell "names no entity"
        # apart from "we don't know this tier's names", and guessing the
        # optimistic way would promote a leading thread to polling. Defer.
        if not self._aliases.covers(plan.entity_granularity):
            return None

        named = self._aliases.find(document.title, plan.entity_granularity)
        if named is not None:
            return TriageDecision(
                document_id=document.id,
                verdict=TriageVerdict.TOPICAL,
                reason=f"title names {named} at the target granularity, so it leads the answer",
                confidence=1.0,
                decided_by=TriageDecidedBy.RULE,
                criterion_match=False,
            )

        if _is_interrogative(document.title):
            return TriageDecision(
                document_id=document.id,
                verdict=TriageVerdict.POLLING,
                reason="an open question naming no entity at the target granularity",
                confidence=1.0,
                decided_by=TriageDecidedBy.RULE,
            )

        return None

    async def _classify(
        self,
        context: PipelineContext,
        plan: ResearchPlan,
        batch: Sequence[SourceDocument],
        floors: TriageFloors,
        *,
        now: datetime,
    ) -> dict[str, TriageDecision]:
        response = await context.llm.complete_structured(
            prompt=build_triage_prompt(plan, batch, now=now),
            response_model=DocumentTriageBatch,
        )
        classified = {item.document_id: item for item in response.items}

        decisions: dict[str, TriageDecision] = {}
        for document in batch:
            item = classified.get(document.id)
            if item is None:
                # Silence is not permission. Keep the thread as evidence,
                # keep its users out of the pool, and say so (plan §0.1).
                context.research.diagnostics.record_suppression(
                    step=self.name,
                    reason=SuppressionReason.TRIAGE_NO_VERDICT,
                    count=1,
                )
                decisions[document.id] = TriageDecision(
                    document_id=document.id,
                    verdict=TriageVerdict.TOPICAL,
                    reason="triage returned no verdict for this document; downgraded to topical",
                    confidence=0.0,
                    decided_by=TriageDecidedBy.AI,
                    downgraded_for_low_confidence=True,
                )
                continue
            decisions[document.id] = _downgrade_only(item, floors)
        return decisions

    def _apply(
        self,
        context: PipelineContext,
        documents: Sequence[SourceDocument],
        decisions: dict[str, TriageDecision],
        floors: TriageFloors,
    ) -> None:
        diagnostics = context.research.diagnostics
        polling: list[SourceDocument] = []
        topical: list[SourceDocument] = []

        for document in documents:
            decision = decisions[document.id]
            if decision.verdict is TriageVerdict.POLLING:
                document.context_type = ContextType.POLLING
                polling.append(document)
            elif decision.verdict is TriageVerdict.TOPICAL:
                document.context_type = ContextType.TOPICAL
                topical.append(document)
            else:
                document.context_type = None
            if decision.verdict is not TriageVerdict.POLLING:
                diagnostics.record_suppression(
                    step=self.name,
                    reason=_SUPPRESSION_REASONS[decision.verdict],
                    count=1,
                    detail=decision.reason,
                )

        diagnostics.triage_decisions = [decisions[document.id] for document in documents]

        excluded = len(documents) - len(polling) - len(topical)
        context.research.statistics["documents_triaged"] = len(documents)
        context.research.statistics["documents_polling"] = len(polling)
        context.research.statistics["documents_topical"] = len(topical)
        context.research.statistics["documents_excluded"] = excluded

        if documents and len(polling) / len(documents) < floors.min_polling_document_ratio:
            diagnostics.raise_flag(ResearchFlag.LOW_POLLING_DOCUMENT_RATIO)

        context.data["polling_documents"] = polling
        context.data["topical_documents"] = topical


def _downgrade_only(item: DocumentTriage, floors: TriageFloors) -> TriageDecision:
    """Turn one AI classification into a decision, downgrading where §4.7 requires it.

    Three overrides, all one-directional:

    * ``polling`` requires ``scope_match and granularity_match``;
    * a thread failing ``criterion_match`` is downgraded rather than
      excluded — it still holds real opinions, they just do not answer
      *this* question (plan §4.7);
    * anything below ``triageConfidenceThreshold`` becomes ``topical``.

    An ``exclude`` verdict below the threshold lands on ``topical`` too.
    That keeps a thread the model was unsure about as evidence while still
    keeping its users out of the respondent pool — the cautious direction in
    both senses, and it never promotes anything to ``polling``.
    """
    verdict = item.verdict
    reason = item.reason
    low_confidence = item.confidence < floors.triage_confidence_threshold

    if low_confidence and verdict is not TriageVerdict.TOPICAL:
        reason = (
            f"{reason} (confidence {item.confidence:.2f} below "
            f"{floors.triage_confidence_threshold:.2f}; downgraded to topical)"
        )
        verdict = TriageVerdict.TOPICAL
    elif verdict is TriageVerdict.POLLING and not (
        item.scope_match and item.granularity_match
    ):
        missing = "scope" if not item.scope_match else "granularity"
        reason = f"{reason} (downgraded to topical: {missing} mismatch)"
        verdict = TriageVerdict.TOPICAL
    elif verdict is TriageVerdict.POLLING and not item.criterion_match:
        reason = f"{reason} (downgraded to topical: does not reflect the research criteria)"
        verdict = TriageVerdict.TOPICAL

    return TriageDecision(
        document_id=item.document_id,
        verdict=verdict,
        reason=reason,
        confidence=item.confidence,
        decided_by=TriageDecidedBy.AI,
        scope_match=item.scope_match,
        granularity_match=item.granularity_match,
        criterion_match=item.criterion_match,
        downgraded_for_low_confidence=low_confidence and item.verdict is not TriageVerdict.TOPICAL,
    )
