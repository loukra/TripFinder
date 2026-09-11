"""Result Summarization (plan §4.6 step 13, `PROJECT.md` Phase 12).

The last AI step, and the only one that runs after the ranking is final. It
fills in :attr:`Result.explanation` for each strong result (plan §4.4) — the
only rankings ever shown as a headline recommendation — grounding every
explanation in the exact quotes behind that entity's counted, positive
opinions (plan §4.1, §5).

**Grounded, not summarized from the corpus at large.** ``PROJECT.md`` Phase
12 asks for "structured evidence, not an uncontrolled dump of the entire
dataset": this step hands the model a capped, per-entity list of
already-verified ``supporting_quote`` strings, never raw comment text or the
whole corpus.

**Missing evidence is not an error.** An entity can rank without any
positive quote surviving triage's and analysis's earlier caps — the pool it
draws from here is smaller than the one that produced its supporter count.
No call is made for it, and the shortfall is recorded rather than left to
look like the model simply had nothing to say (plan §0.1).

**Hallucination safeguard, the mirror of §5's quote verification.** Every
explanation must cite the quotes it drew on, and a cited quote that is not
one of the ones this entity was given makes the whole explanation unusable
— discarded, not trimmed, because unlike a single mention (§5's unit), an
explanation is one claim and cannot be partially trusted. `PROJECT.md` §29:
never silently invent evidence.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from typing import NamedTuple

from tripfinder.analysis.entity_resolution import ResolvedMention
from tripfinder.analysis.summarization import (
    EntityEvidence,
    EntitySummary,
    EntitySummaryBatch,
    build_summarization_prompt,
)
from tripfinder.domain.models import Result, Stance, SuppressionReason
from tripfinder.pipeline.base import PipelineContext

logger = logging.getLogger(__name__)

DEFAULT_SUMMARIZATION_BATCH_SIZE = 10
"""Entities per structured call."""

DEFAULT_MAX_QUOTES_PER_ENTITY = 8
"""Caps the evidence handed to the model per entity (`PROJECT.md` Phase 12:
structured evidence, not an uncontrolled dump)."""


class _BatchResult(NamedTuple):
    """What one structured call produced, and what it cost in unusable answers."""

    summaries: dict[str, EntitySummary]
    fabricated_ids: frozenset[str]
    """Entities whose returned explanation cited a quote it was not given."""

    discarded: int
    """Items that named no entity in the batch, or named one twice."""


def _comparable(quote: str) -> str:
    """One quote, as it is compared: same words, whitespace collapsed."""
    return " ".join(quote.split())


def _batched(
    entities: Sequence[EntityEvidence], size: int
) -> Iterator[Sequence[EntityEvidence]]:
    for start in range(0, len(entities), size):
        yield entities[start : start + size]


class SummarizationStep:
    """Real implementation of plan §4.6 step 13."""

    name = "summarization"

    def __init__(
        self,
        *,
        batch_size: int = DEFAULT_SUMMARIZATION_BATCH_SIZE,
        max_quotes_per_entity: int = DEFAULT_MAX_QUOTES_PER_ENTITY,
    ) -> None:
        self._batch_size = batch_size
        self._max_quotes_per_entity = max_quotes_per_entity

    async def run(self, context: PipelineContext) -> PipelineContext:
        results: list[Result] = context.research.results
        evidence_by_entity = self._collect_evidence(context)
        with_evidence = [
            EntityEvidence(
                entity_id=result.entity_id,
                entity_name=result.entity_name,
                quotes=evidence_by_entity[result.entity_id],
            )
            for result in results
            if evidence_by_entity.get(result.entity_id)
        ]
        no_evidence = len(results) - len(with_evidence)

        summaries: dict[str, EntitySummary] = {}
        fabricated_ids: set[str] = set()
        discarded = 0
        for batch in _batched(with_evidence, self._batch_size):
            batch_result = await self._summarize(context, batch)
            summaries.update(batch_result.summaries)
            fabricated_ids |= batch_result.fabricated_ids
            discarded += batch_result.discarded

        for result in results:
            summary = summaries.get(result.entity_id)
            if summary is not None:
                result.explanation = summary.explanation

        requested_ids = {evidence.entity_id for evidence in with_evidence}
        missing_ids = requested_ids - summaries.keys() - fabricated_ids

        self._record(
            context,
            no_evidence=no_evidence,
            missing=len(missing_ids),
            fabricated=len(fabricated_ids),
            discarded=discarded,
        )
        return context

    def _collect_evidence(self, context: PipelineContext) -> dict[str, list[str]]:
        """Verified quotes behind each entity's *counted*, positive opinions.

        ``counted_resolutions`` is Entity Resolution's pre-dedup output for
        the polling corpus (plan §4.6 step 8) — every stance survives there,
        so this filters to ``positive`` itself rather than trusting the
        upstream list to already mean "recommended".
        """
        resolutions: Sequence[ResolvedMention] = context.data.get("counted_resolutions", [])
        quotes: dict[str, list[str]] = {}
        for resolution in resolutions:
            if resolution.mention.stance is not Stance.POSITIVE:
                continue
            bucket = quotes.setdefault(resolution.entity.canonical_id, [])
            quote = resolution.mention.supporting_quote
            if quote in bucket or len(bucket) >= self._max_quotes_per_entity:
                continue
            bucket.append(quote)
        return quotes

    async def _summarize(
        self, context: PipelineContext, batch: Sequence[EntityEvidence]
    ) -> _BatchResult:
        """One structured call, matched back to the entities it was asked about."""
        response = await context.llm.complete_structured(
            prompt=build_summarization_prompt(batch),
            response_model=EntitySummaryBatch,
        )
        requested = {evidence.entity_id: evidence for evidence in batch}

        summaries: dict[str, EntitySummary] = {}
        fabricated_ids: set[str] = set()
        discarded = 0
        for item in response.items:
            evidence = requested.get(item.entity_id)
            if evidence is None:
                # An explanation for an entity this batch never contained.
                # It cannot be attributed to any evidence we hold, so it is
                # not usable (plan §5's rule, applied here too).
                logger.warning(
                    "summarization: dropping an item for unrequested entity %s",
                    item.entity_id,
                )
                discarded += 1
                continue
            if item.entity_id in summaries or item.entity_id in fabricated_ids:
                logger.warning(
                    "summarization: dropping a duplicate item for entity %s", item.entity_id
                )
                discarded += 1
                continue
            if not self._is_grounded(item, evidence):
                logger.warning(
                    "summarization: discarding the explanation for %s — it cites a "
                    "quote not drawn from its stored evidence: %s",
                    evidence.entity_name,
                    [quote[:90] for quote in item.cited_quotes] or "(no quote cited at all)",
                )
                fabricated_ids.add(item.entity_id)
                continue
            summaries[item.entity_id] = item

        return _BatchResult(
            summaries=summaries, fabricated_ids=frozenset(fabricated_ids), discarded=discarded
        )

    def _is_grounded(self, item: EntitySummary, evidence: EntityEvidence) -> bool:
        """Every cited quote must be one this entity was actually given.

        Compared with runs of whitespace collapsed, on both sides. The rule
        this enforces (`PROJECT.md` §29) is *"the model may not cite what it
        was not given"* — a claim about the words, not about the line breaks
        between them. A comment quoted across two paragraphs comes back from
        the model re-wrapped, which is not fabrication and must not be
        reported as it; a paraphrase still fails, because collapsing
        whitespace changes no word.
        """
        if not item.cited_quotes:
            return False
        known = {_comparable(quote) for quote in evidence.quotes}
        return all(_comparable(quote) in known for quote in item.cited_quotes)

    def _record(
        self,
        context: PipelineContext,
        *,
        no_evidence: int,
        missing: int,
        fabricated: int,
        discarded: int,
    ) -> None:
        diagnostics = context.research.diagnostics
        diagnostics.record_suppression(
            step=self.name,
            reason=SuppressionReason.SUMMARIZATION_NO_EVIDENCE,
            count=no_evidence,
            detail="no stored evidence to ground an explanation",
        )
        diagnostics.record_suppression(
            step=self.name,
            reason=SuppressionReason.SUMMARIZATION_NO_RESULT,
            count=missing,
            detail="summarization call returned no explanation for this entity",
        )
        diagnostics.record_suppression(
            step=self.name,
            reason=SuppressionReason.SUMMARIZATION_FABRICATED_QUOTE,
            count=fabricated,
            detail="explanation discarded — it cited a quote not drawn from stored evidence",
        )

        results = context.research.results
        statistics = context.research.statistics
        statistics["results_explained"] = sum(1 for r in results if r.explanation is not None)
        statistics["results_without_evidence"] = no_evidence
        statistics["results_without_summary"] = missing
        statistics["summarization_fabricated_quote"] = fabricated
        statistics["summarization_items_discarded"] = discarded
