"""Entity Resolution (plan §4.6 step 8, `PROJECT.md` §15).

Comment analysis leaves behind names as people wrote them — *Alaska*,
*AK*, *the Last Frontier*, *Hawai'i*, *the Beaver State*. This step decides
which of them are the same place, because until it does, the count in §4.2
is counting spellings rather than destinations.

Plan §4.6 fixes the order, and it is an order of increasing risk:

1. **Deterministic normalization** folds case, accents and punctuation
   (``analysis/normalization.py``). It can only ever match a name to
   itself written differently.
2. **The alias table** (``analysis/entities.py``) turns a known name into a
   known entity. Exact, auditable, free.
3. **The model**, and only for what the first two could not settle — a
   nickname we do not hold, a misspelling, a name two places share.

Three rules keep step 3 from becoming the weak point.

**Only ambiguity reaches it.** Everything the catalogue resolves is settled
before a token is spent, so a corpus of forty thousand mentions asks about
whatever handful of names remain.

**The model proposes a name, never a merge.** Its answer goes back through
the same lookup the deterministic half used, and *that* decides which
entity it is — or that it is still ambiguous, in which case nothing is
merged. Where the name was ambiguous to begin with, the answer must be one
of the candidates we offered; anything else is refused.

**Below ``confidence_threshold`` nothing is merged at all** (`PROJECT.md`
§15). The name is recorded as unresolved, with the model's own reason.

**Nothing is silently dropped** (plan §0.1). Every surface form the run
could not place is recorded in ``diagnostics.entity_resolutions`` with its
occurrence count and the reason, and the mentions behind it are counted as
suppressions. A ranking built from ten resolved names out of a hundred is
then visibly different from one built from ten out of ten.

**Scope.** Resolution runs at the plan's target granularity, because that
is the tier §4.1 draws the respondent pool from — a park named in a
question about states cannot produce a counted opinion whatever we resolve
it to. Such mentions are recorded as ``entity_off_granularity`` rather than
resolved, so they cost no model call and still appear in the diagnostics.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from tripfinder.analysis.catalogs import default_catalog
from tripfinder.analysis.comment_analysis import CommentAnalysis, EntityMention
from tripfinder.analysis.entities import CatalogEntry, EntityCatalog
from tripfinder.analysis.entity_resolution import (
    EntityResolutionBatch,
    ResolutionQuestion,
    ResolvedMention,
    ResolvedName,
    build_entity_resolution_prompt,
)
from tripfinder.analysis.normalization import slug
from tripfinder.domain.config import EntityResolutionConfig
from tripfinder.domain.models import (
    Entity,
    EntityResolutionMethod,
    EntityResolutionOutcome,
    EntityType,
    ResearchPlan,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.streaming.resolution import ResolutionCache

logger = logging.getLogger(__name__)

DEFAULT_RESOLUTION_BATCH_SIZE = 50
"""Distinct surface forms per structured call."""

_FormKey = tuple[str, EntityType]
"""Identifies one distinct surface form: its exact text and the tier it named."""


@dataclass
class _Form:
    """One distinct way the corpus wrote a name, and every mention using it."""

    surface_form: str
    entity_type: EntityType
    example_quote: str
    occurrences: int = 0
    candidates: tuple[CatalogEntry, ...] = field(default_factory=tuple)
    """What the alias table matched. More than one means ambiguous."""


@dataclass(frozen=True)
class _Verdict:
    """What became of one form: an entity, or a reason there is none."""

    entity: Entity | None
    decided_by: EntityResolutionMethod
    confidence: float
    reason: str
    suppression: SuppressionReason | None = None


def resolution_cache(context: PipelineContext) -> ResolutionCache | None:
    """The run's shared store of names the model has already placed, if it has one.

    Absent outside a streaming run — a step asked to resolve a corpus with
    no cache behaves exactly as it did before there was one.
    """
    cache = context.data.get("resolution_cache")
    return cache if isinstance(cache, ResolutionCache) else None


def _key(mention: EntityMention) -> _FormKey:
    """Surface forms group verbatim — casing is what tells ``AK`` from ``ak``."""
    return (mention.raw_text, mention.entity_type)


def _batched(
    questions: Sequence[ResolutionQuestion], size: int
) -> Iterator[Sequence[ResolutionQuestion]]:
    for start in range(0, len(questions), size):
        yield questions[start : start + size]


def _resolved(
    entity: Entity, by: EntityResolutionMethod, reason: str, confidence: float
) -> _Verdict:
    return _Verdict(entity=entity, decided_by=by, confidence=confidence, reason=reason)


def _unresolved(
    by: EntityResolutionMethod,
    reason: str,
    suppression: SuppressionReason,
    confidence: float = 0.0,
) -> _Verdict:
    return _Verdict(
        entity=None,
        decided_by=by,
        confidence=confidence,
        reason=reason,
        suppression=suppression,
    )


class EntityResolutionStep:
    """Real implementation of plan §4.6 step 8."""

    name = "entity_resolution"

    def __init__(
        self,
        catalog: EntityCatalog | None = None,
        *,
        batch_size: int = DEFAULT_RESOLUTION_BATCH_SIZE,
        ask_model: bool = True,
    ) -> None:
        """``ask_model=False`` is the provisional mode plan §2.13 runs snapshots in.

        It does two things, and both matter. The model is not asked — a
        snapshot after every analysis batch cannot afford a call, and a name
        the catalogue cannot place is left uncounted rather than guessed at,
        so a snapshot under-reports, which is the safe direction. And
        nothing is written to diagnostics: a snapshot decides nothing about
        the run (§2.13.2), so this step's record of what it could not place
        would be a record of a corpus that never existed.
        """
        self._catalog = catalog if catalog is not None else default_catalog()
        self._batch_size = batch_size
        self._ask_model = ask_model

    async def run(self, context: PipelineContext) -> PipelineContext:
        plan: ResearchPlan = context.data["plan"]
        config = context.research.research_config.entity_resolution
        counted: list[CommentAnalysis] = list(context.data.get("counted_analyses", []))
        evidence: list[CommentAnalysis] = list(context.data.get("evidence_analyses", []))

        forms = self._collect(counted + evidence)
        verdicts = {key: self._pre_check(form, plan) for key, form in forms.items()}

        questions = [
            _question(forms[key]) for key, verdict in verdicts.items() if verdict is None
        ]
        verdicts.update(await self._settle(context, plan, questions, config))

        settled = {key: verdict for key, verdict in verdicts.items() if verdict is not None}
        entities = _registry(settled.values())
        counted_resolutions = self._join(counted, settled, entities)
        evidence_resolutions = self._join(evidence, settled, entities)

        context.data["counted_resolutions"] = counted_resolutions
        context.data["evidence_resolutions"] = evidence_resolutions
        context.data["resolved_mentions"] = counted_resolutions + evidence_resolutions
        context.data["entities"] = [entities[key] for key in sorted(entities)]

        if self._ask_model:
            self._record(context, forms, settled)
        return context

    # -- 1. group ------------------------------------------------------

    def _collect(self, analyses: Sequence[CommentAnalysis]) -> dict[_FormKey, _Form]:
        """Every mention, grouped by the surface form it used, in first-seen order."""
        forms: dict[_FormKey, _Form] = {}
        for analysis in analyses:
            for mention in analysis.mentions:
                form = forms.get(_key(mention))
                if form is None:
                    form = _Form(
                        surface_form=mention.raw_text,
                        entity_type=mention.entity_type,
                        example_quote=mention.supporting_quote,
                    )
                    forms[_key(mention)] = form
                form.occurrences += 1
        return forms

    # -- 2. deterministic ----------------------------------------------

    def _pre_check(self, form: _Form, plan: ResearchPlan) -> _Verdict | None:
        """Settle what the catalogue can. ``None`` means "ask the model".

        Records what the lookup matched on the form as it goes: an
        unsettled form carries its candidates into the question, so the
        model chooses between the places we hold rather than inventing one.
        """
        if form.entity_type is not plan.entity_granularity:
            return _unresolved(
                EntityResolutionMethod.RULE,
                f"a {form.entity_type.value}, not a {plan.entity_granularity.value} — "
                f"kept as evidence, but it cannot answer this question",
                SuppressionReason.ENTITY_OFF_GRANULARITY,
                confidence=1.0,
            )

        # Only the wording the commenter used is looked up. Phase 8 used to
        # also send a model-guessed canonical name, and a hit on *that* was
        # recorded as RULE at confidence 1.0 — a model's judgement wearing a
        # catalogue's badge, and §2.12.1 showed the model guesses wrong names
        # confidently. An alias the catalogue does not hold now goes to the
        # model below, which is where a judgement belongs (§2.12, 14.6a).
        matches = self._catalog.lookup(form.surface_form, plan.entity_granularity)
        form.candidates = matches

        if len(matches) == 1:
            return _resolved(
                matches[0].as_entity(),
                EntityResolutionMethod.RULE,
                f"a known name for {matches[0].canonical_name}",
                confidence=1.0,
            )
        return None

    # -- 3. the model, for the remainder --------------------------------

    async def _settle(
        self,
        context: PipelineContext,
        plan: ResearchPlan,
        questions: Sequence[ResolutionQuestion],
        config: EntityResolutionConfig,
    ) -> dict[_FormKey, _Verdict]:
        """Decide the forms the catalogue could not, from the cache or the model.

        The cache is what makes a provisional ranking possible at all for a
        question the catalogue does not cover (``streaming/resolution.py``):
        a form already put to the model is settled here **without a call**,
        in snapshot mode exactly as in the final one, by the same
        :meth:`_apply`. What is left over is asked for only when this step
        is allowed to ask; otherwise it stays unresolved, and the snapshot
        under-reports in the direction plan §2.13.1 requires.
        """
        cache = resolution_cache(context)
        known: list[ResolutionQuestion] = []
        missing: list[ResolutionQuestion] = []
        answers: dict[str, ResolvedName] = {}
        for question in questions:
            cached = cache.answer(question.surface_form) if cache is not None else None
            if cache is not None and cache.knows(question.surface_form):
                known.append(question)
                if cached is not None:
                    answers[question.surface_form] = cached
            else:
                missing.append(question)

        if self._ask_model and missing:
            answers.update(await self._ask(context, plan, missing, config))
            decided = questions
        else:
            decided = known

        verdicts = {
            (question.surface_form, question.entity_type): self._apply(
                question, answers.get(question.surface_form), config, plan
            )
            for question in decided
        }
        if not self._ask_model:
            verdicts.update(_unasked(missing))
        return verdicts

    async def prime(
        self,
        context: PipelineContext,
        *,
        counted_analyses: Sequence[CommentAnalysis],
        evidence_analyses: Sequence[CommentAnalysis],
    ) -> int:
        """Put this corpus's unplaced names to the model, into the cache only.

        Called while analysis is still running (``streaming/accumulator.py``),
        with the corpus passed in rather than read from ``context.data``,
        because during a streaming run that key does not exist yet.

        It decides nothing. No resolution, no entity, no diagnostic and no
        status is written — those belong to the run's own pass over a closed
        corpus (plan §2.13.2). The one thing it does record is how many
        malformed answers it threw away, because that is a count of what
        *this run* discarded in calls it genuinely made, and §0.1 does not
        exempt a call for being early.

        **The first call is made as soon as there is anything to place**,
        however little — a run must not have to raise fifty names before it
        can show one, and a question whose whole corpus names a dozen places
        would otherwise never preview at all. After that, only whole batches
        are asked for: a cache that called after every analysis batch would
        turn a run's thirteen resolution calls into seventy, and cost is the
        other complaint this codebase has to answer. Whatever is still
        partial when analysis ends is swept up by this step's own final
        pass — the same remainder it always asked for.
        """
        cache = resolution_cache(context)
        if cache is None:
            return 0

        plan: ResearchPlan = context.data["plan"]
        forms = self._collect([*counted_analyses, *evidence_analyses])
        questions = [
            _question(form)
            for key, form in forms.items()
            if self._pre_check(form, plan) is None and not cache.knows(form.surface_form)
        ]
        whole = len(questions) - len(questions) % self._batch_size
        if whole == 0:
            if cache or not questions:
                return 0
            whole = len(questions)  # the run's first names, however few

        config = context.research.research_config.entity_resolution
        await self._ask(context, plan, questions[:whole], config)
        return whole

    async def _ask(
        self,
        context: PipelineContext,
        plan: ResearchPlan,
        questions: Sequence[ResolutionQuestion],
        config: EntityResolutionConfig,
    ) -> dict[str, ResolvedName]:
        """Put these forms to the model, a batch at a time, and remember the answers.

        Every batch is written to the cache as it lands rather than at the
        end, so a call that fails half way through leaves the run better
        informed than it found it — and a snapshot taken in between sees the
        names that *have* been placed.
        """
        if not questions:
            return {}

        cache = resolution_cache(context)
        answers: dict[str, ResolvedName] = {}
        discarded = 0
        for batch in _batched(questions, self._batch_size):
            asked = {question.surface_form for question in batch}
            response = await context.llm.complete_structured(
                prompt=build_entity_resolution_prompt(plan, batch),
                response_model=EntityResolutionBatch,
            )
            landed: dict[str, ResolvedName] = {}
            for item in response.items:
                if item.surface_form not in asked or item.surface_form in answers:
                    logger.warning(
                        "resolution: dropping an answer for %r — not asked, or answered twice",
                        item.surface_form,
                    )
                    discarded += 1
                    continue
                landed[item.surface_form] = item
            answers.update(landed)
            if cache is not None:
                cache.remember(asked, landed)

        # Accumulated, not assigned: priming asks in several passes while
        # analysis runs, and a malformed answer discarded during one of them
        # is as much a suppression as one discarded during the last (§0.1).
        statistics = context.research.statistics
        statistics["entity_resolution_items_discarded"] = (
            statistics.get("entity_resolution_items_discarded", 0) + discarded
        )
        return answers

    def _apply(
        self,
        question: ResolutionQuestion,
        answer: ResolvedName | None,
        config: EntityResolutionConfig,
        plan: ResearchPlan,
    ) -> _Verdict:
        """Turn one model answer into a verdict — deterministically, and cautiously."""
        ambiguous = bool(question.candidates)
        unmerged = (
            SuppressionReason.ENTITY_AMBIGUOUS if ambiguous else SuppressionReason.ENTITY_UNRESOLVED
        )

        if answer is None:
            return _unresolved(
                EntityResolutionMethod.AI,
                "resolution returned no answer for this name, so it was not merged",
                SuppressionReason.ENTITY_RESOLUTION_NO_RESULT,
            )
        proposed = (answer.canonical_name or "").strip()
        if not slug(proposed):
            return _unresolved(
                EntityResolutionMethod.AI, answer.reason, unmerged, answer.confidence
            )
        if answer.confidence < config.confidence_threshold:
            return _unresolved(
                EntityResolutionMethod.AI,
                f"{answer.reason} (confidence {answer.confidence:.2f} below "
                f"{config.confidence_threshold:.2f}; not merged)",
                unmerged,
                answer.confidence,
            )

        matches = self._catalog.lookup(proposed, plan.entity_granularity)
        if len(matches) > 1:
            return _unresolved(
                EntityResolutionMethod.AI,
                f"{answer.reason} (the name it gave, {proposed!r}, is itself "
                f"shared by {len(matches)} places; not merged)",
                SuppressionReason.ENTITY_AMBIGUOUS,
                answer.confidence,
            )
        if ambiguous and (not matches or matches[0].canonical_name not in question.candidates):
            return _unresolved(
                EntityResolutionMethod.AI,
                f"{answer.reason} (answered {proposed!r}, which is none of the "
                f"places this name could mean; not merged)",
                SuppressionReason.ENTITY_AMBIGUOUS,
                answer.confidence,
            )
        if matches:
            return _resolved(
                matches[0].as_entity(),
                EntityResolutionMethod.AI,
                answer.reason,
                answer.confidence,
            )

        return _resolved(
            _mint(proposed, question.entity_type),
            EntityResolutionMethod.AI,
            f"{answer.reason} (not in the alias table; held as a new entity)",
            answer.confidence,
        )

    # -- 4. output and accounting ---------------------------------------

    def _join(
        self,
        analyses: Sequence[CommentAnalysis],
        verdicts: dict[_FormKey, _Verdict],
        entities: dict[str, Entity],
    ) -> list[ResolvedMention]:
        """The mentions that reached an entity, in the order they were analysed.

        Two surface forms of one place share the entity object, so *AK* and
        *the Last Frontier* are Alaska once, not twice.
        """
        resolved: list[ResolvedMention] = []
        for analysis in analyses:
            for mention in analysis.mentions:
                entity = verdicts[_key(mention)].entity
                if entity is not None:
                    resolved.append(
                        ResolvedMention(
                            comment_id=analysis.comment_id,
                            mention=mention,
                            entity=entities[entity.canonical_id],
                        )
                    )
        return resolved

    def _record(
        self,
        context: PipelineContext,
        forms: dict[_FormKey, _Form],
        verdicts: dict[_FormKey, _Verdict],
    ) -> None:
        """Plan §0.1: every name this step could not place, said out loud."""
        diagnostics = context.research.diagnostics
        outcomes: list[EntityResolutionOutcome] = []
        resolved_mentions = 0
        off_granularity = 0
        unresolved_mentions = 0
        by_rule = 0
        by_ai = 0

        for key, form in forms.items():
            verdict = verdicts[key]
            entity = verdict.entity
            outcomes.append(
                EntityResolutionOutcome(
                    surface_form=form.surface_form,
                    entity_type=form.entity_type,
                    occurrences=form.occurrences,
                    entity_id=None if entity is None else entity.canonical_id,
                    canonical_name=None if entity is None else entity.canonical_name,
                    decided_by=verdict.decided_by,
                    confidence=verdict.confidence,
                    reason=verdict.reason,
                )
            )
            if entity is not None:
                resolved_mentions += form.occurrences
                if verdict.decided_by is EntityResolutionMethod.RULE:
                    by_rule += 1
                else:
                    by_ai += 1
            elif verdict.suppression is SuppressionReason.ENTITY_OFF_GRANULARITY:
                off_granularity += form.occurrences
            else:
                unresolved_mentions += form.occurrences

            if verdict.suppression is not None:
                diagnostics.record_suppression(
                    step=self.name,
                    reason=verdict.suppression,
                    count=form.occurrences,
                    detail=f"{form.surface_form}: {verdict.reason}",
                )

        diagnostics.entity_resolutions = outcomes

        statistics = context.research.statistics
        statistics["entity_forms_total"] = len(forms)
        statistics["entity_forms_resolved_by_rule"] = by_rule
        statistics["entity_forms_resolved_by_ai"] = by_ai
        statistics["entity_forms_unresolved"] = len(forms) - by_rule - by_ai
        statistics["entity_mentions_total"] = sum(form.occurrences for form in forms.values())
        statistics["entity_mentions_resolved"] = resolved_mentions
        statistics["entity_mentions_unresolved"] = unresolved_mentions
        statistics["entity_mentions_off_granularity"] = off_granularity
        statistics["entities_resolved"] = len(context.data["entities"])
        statistics.setdefault("entity_resolution_items_discarded", 0)


def _unasked(questions: Sequence[ResolutionQuestion]) -> dict[_FormKey, _Verdict]:
    """What becomes of an ambiguous name when the model is not asked at all.

    Nothing is merged and nothing is guessed, so these names contribute no
    supporters to a snapshot. The count it shows is therefore a floor on the
    count the finished run will show — which is what plan §2.13.1 promises a
    provisional number is.
    """
    return {
        (question.surface_form, question.entity_type): _unresolved(
            EntityResolutionMethod.RULE,
            "the catalogue could not place this name, and a provisional ranking "
            "does not ask the model — not counted here",
            SuppressionReason.ENTITY_UNRESOLVED,
        )
        for question in questions
    }


def _question(form: _Form) -> ResolutionQuestion:
    return ResolutionQuestion(
        surface_form=form.surface_form,
        entity_type=form.entity_type,
        example_quote=form.example_quote,
        candidates=tuple(entry.canonical_name for entry in form.candidates),
    )


def _mint(canonical_name: str, entity_type: EntityType) -> Entity:
    """An entity for a real place the alias table does not hold.

    Its id comes from its name, so two comments that arrive at the same
    canonical name arrive at the same entity — and so the same corpus
    produces the same ids on every run (plan §4.3).
    """
    return Entity(
        canonical_id=f"{entity_type.value}:{slug(canonical_name)}",
        canonical_name=canonical_name,
        entity_type=entity_type,
    )


def _registry(verdicts: Iterable[_Verdict]) -> dict[str, Entity]:
    """One entity object per canonical id, so identity is the id and nothing else."""
    entities: dict[str, Entity] = {}
    for verdict in verdicts:
        if verdict.entity is not None:
            entities.setdefault(verdict.entity.canonical_id, verdict.entity)
    return entities
