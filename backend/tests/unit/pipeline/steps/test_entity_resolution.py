"""Entity Resolution (plan §4.6 step 8, `PROJECT.md` §15, §27 Phase 9).

`PROJECT.md` §27 names the cases: aliases, abbreviations, spelling
differences, ambiguous regions, unrelated mentions. Each has a class below,
in that order, followed by the two rules that hold the step together — the
model may propose a name but never a merge, and nothing this step drops
disappears quietly (plan §0.1).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import BaseModel

from builders.phase7 import make_context, make_plan
from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.analysis.comment_analysis import CommentAnalysis, EntityMention
from tripfinder.analysis.entities import Alias, CatalogEntry, EntityCatalog
from tripfinder.analysis.entity_resolution import EntityResolutionBatch, ResolvedName
from tripfinder.domain.config import EntityResolutionConfig, ResearchConfig
from tripfinder.domain.models import (
    EntityResolutionMethod,
    EntityResolutionOutcome,
    EntityType,
    ReasonCode,
    ResearchStatus,
    Stance,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.entity_resolution import EntityResolutionStep

SPRINGFIELD_OR = CatalogEntry(
    "Springfield, Oregon", EntityType.STATE, (Alias("Springfield"),)
)
SPRINGFIELD_IL = CatalogEntry(
    "Springfield, Illinois", EntityType.STATE, (Alias("Springfield"),)
)
AMBIGUOUS_CATALOG = EntityCatalog([SPRINGFIELD_OR, SPRINGFIELD_IL])


class RecordingLLM:
    """Wraps the fake provider and keeps every prompt it was asked to answer."""

    def __init__(self, responses: Sequence[EntityResolutionBatch] = ()) -> None:
        self._inner = FakeLLMProvider({EntityResolutionBatch: list(responses)})
        self.prompts: list[str] = []

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        self.prompts.append(prompt)
        return await self._inner.complete_structured(prompt=prompt, response_model=response_model)


def mention(
    raw_text: str,
    *,
    entity_type: EntityType = EntityType.STATE,
    quote: str = "a verbatim span",
) -> EntityMention:
    return EntityMention(
        raw_text=raw_text,
        entity_type=entity_type,
        stance=Stance.POSITIVE,
        strength=0.8,
        supporting_quote=quote,
    )


def analysis(comment_id: str, *mentions: EntityMention) -> CommentAnalysis:
    return CommentAnalysis(
        comment_id=comment_id,
        topic_relevance=0.9,
        criterion_relevance=0.9,
        scope_match=True,
        overall_confidence=0.9,
        mentions=list(mentions),
        reason_code=ReasonCode.RECOMMENDS,
    )


def answer(surface_form: str, canonical_name: str | None, confidence: float) -> ResolvedName:
    return ResolvedName(
        surface_form=surface_form,
        canonical_name=canonical_name,
        confidence=confidence,
        reason="fixture answer",
    )


def context_with(
    *,
    counted: Sequence[CommentAnalysis] = (),
    evidence: Sequence[CommentAnalysis] = (),
    llm: RecordingLLM | None = None,
    config: ResearchConfig | None = None,
    granularity: EntityType = EntityType.STATE,
) -> PipelineContext:
    context = make_context(
        llm=llm or RecordingLLM(), config=config, status=ResearchStatus.ANALYZING
    )
    context.data["plan"] = make_plan(granularity)
    context.data["counted_analyses"] = list(counted)
    context.data["evidence_analyses"] = list(evidence)
    return context


def names(context: PipelineContext) -> list[str]:
    return [entity.canonical_name for entity in context.data["entities"]]


def resolved_names(context: PipelineContext, key: str = "counted_resolutions") -> list[str]:
    return [resolution.entity.canonical_name for resolution in context.data[key]]


def outcome(context: PipelineContext, surface_form: str) -> EntityResolutionOutcome:
    for entry in context.research.diagnostics.entity_resolutions:
        if entry.surface_form == surface_form:
            return entry
    raise LookupError(surface_form)


def suppressed(context: PipelineContext, reason: SuppressionReason) -> int:
    return sum(
        entry.count
        for entry in context.research.diagnostics.suppressions
        if entry.reason is reason
    )


class TestAliases:
    async def test_a_known_name_resolves_with_no_model_call(self) -> None:
        """The point of resolving deterministically first: the model is never asked."""
        llm = RecordingLLM()
        context = context_with(counted=[analysis("c1", mention("Alaska"))], llm=llm)

        await EntityResolutionStep().run(context)

        assert llm.prompts == []
        assert names(context) == ["Alaska"]

    async def test_a_nickname_and_the_name_are_one_entity(self) -> None:
        """`PROJECT.md` §15's own example: *Alaska* and *The Last Frontier*."""
        context = context_with(
            counted=[
                analysis("c1", mention("Alaska")),
                analysis("c2", mention("The Last Frontier")),
            ]
        )

        await EntityResolutionStep().run(context)

        assert names(context) == ["Alaska"]
        assert resolved_names(context) == ["Alaska", "Alaska"]

    async def test_resolved_mentions_share_one_entity_object(self) -> None:
        context = context_with(
            counted=[analysis("c1", mention("Alaska"), mention("the last frontier"))]
        )

        await EntityResolutionStep().run(context)

        first, second = context.data["counted_resolutions"]
        assert first.entity is second.entity

    async def test_the_entity_id_is_derived_from_the_name(self) -> None:
        context = context_with(counted=[analysis("c1", mention("New Mexico"))])

        await EntityResolutionStep().run(context)

        assert context.data["entities"][0].canonical_id == "state:new-mexico"


class TestAbbreviations:
    async def test_a_postal_abbreviation_resolves_to_its_state(self) -> None:
        context = context_with(
            counted=[analysis("c1", mention("AK")), analysis("c2", mention("Alaska"))]
        )

        await EntityResolutionStep().run(context)

        assert names(context) == ["Alaska"]
        assert outcome(context, "AK").decided_by is EntityResolutionMethod.RULE

    async def test_a_lowercase_conjunction_is_not_a_state(self) -> None:
        """*or* reaching the catalogue as Oregon would invent supporters."""
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("or", None, 0.1)])])
        context = context_with(counted=[analysis("c1", mention("or"))], llm=llm)

        await EntityResolutionStep().run(context)

        assert names(context) == []
        assert llm.prompts != []


class TestSpellingDifferences:
    async def test_an_apostrophe_spelling_resolves_deterministically(self) -> None:
        llm = RecordingLLM()
        context = context_with(counted=[analysis("c1", mention("Hawai'i"))], llm=llm)

        await EntityResolutionStep().run(context)

        assert names(context) == ["Hawaii"]
        assert llm.prompts == []

    async def test_a_misspelling_falls_through_to_the_model(self) -> None:
        """Nothing deterministic can fold *Massachussetts* — that is what the model is for."""
        llm = RecordingLLM(
            [EntityResolutionBatch(items=[answer("Massachussetts", "Massachusetts", 0.95)])]
        )
        context = context_with(counted=[analysis("c1", mention("Massachussetts"))], llm=llm)

        await EntityResolutionStep().run(context)

        assert names(context) == ["Massachusetts"]
        assert outcome(context, "Massachussetts").decided_by is EntityResolutionMethod.AI
        assert outcome(context, "Massachussetts").entity_id == "state:massachusetts"

    async def test_a_misspelling_and_its_correct_form_become_one_entity(self) -> None:
        llm = RecordingLLM(
            [EntityResolutionBatch(items=[answer("Massachussetts", "Massachusetts", 0.95)])]
        )
        context = context_with(
            counted=[
                analysis("c1", mention("Massachussetts")),
                analysis("c2", mention("Massachusetts")),
            ],
            llm=llm,
        )

        await EntityResolutionStep().run(context)

        assert names(context) == ["Massachusetts"]
        assert len(context.data["counted_resolutions"]) == 2


class TestAmbiguousRegions:
    def _catalog_step(self) -> EntityResolutionStep:
        return EntityResolutionStep(AMBIGUOUS_CATALOG)

    async def test_an_ambiguous_name_is_put_to_the_model_with_its_candidates(self) -> None:
        llm = RecordingLLM(
            [EntityResolutionBatch(items=[answer("Springfield", "Springfield, Oregon", 0.9)])]
        )
        context = context_with(counted=[analysis("c1", mention("Springfield"))], llm=llm)

        await self._catalog_step().run(context)

        assert "Springfield, Oregon, Springfield, Illinois" in llm.prompts[0]
        assert names(context) == ["Springfield, Oregon"]

    async def test_an_ambiguous_name_the_model_cannot_settle_is_not_merged(self) -> None:
        """The `PROJECT.md` §15 rule: never silently merge (plan §0.1 rule 1)."""
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("Springfield", None, 0.2)])])
        context = context_with(counted=[analysis("c1", mention("Springfield"))], llm=llm)

        await self._catalog_step().run(context)

        assert names(context) == []
        assert context.data["counted_resolutions"] == []
        assert suppressed(context, SuppressionReason.ENTITY_AMBIGUOUS) == 1
        assert outcome(context, "Springfield").entity_id is None

    async def test_the_model_may_only_pick_from_the_candidates_offered(self) -> None:
        """An answer outside the candidate set is a reinterpretation, not a resolution."""
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("Springfield", "Oregon", 0.99)])])
        context = context_with(counted=[analysis("c1", mention("Springfield"))], llm=llm)

        await self._catalog_step().run(context)

        assert names(context) == []
        assert "none of the places this name could mean" in outcome(context, "Springfield").reason
        assert suppressed(context, SuppressionReason.ENTITY_AMBIGUOUS) == 1

    async def test_a_name_the_model_answers_with_is_itself_checked_for_ambiguity(self) -> None:
        """An unknown form answered with a name two places share resolves nothing."""
        llm = RecordingLLM(
            [EntityResolutionBatch(items=[answer("that Simpsons town", "Springfield", 0.95)])]
        )
        context = context_with(counted=[analysis("c1", mention("that Simpsons town"))], llm=llm)

        await self._catalog_step().run(context)

        assert names(context) == []
        assert "is itself shared by 2 places" in outcome(context, "that Simpsons town").reason


class TestUnrelatedMentions:
    async def test_a_mention_at_another_granularity_is_recorded_not_resolved(self) -> None:
        """A park cannot answer a question about states (plan §4.1's pool tier)."""
        llm = RecordingLLM()
        context = context_with(
            counted=[analysis("c1", mention("Denali", entity_type=EntityType.PARK))], llm=llm
        )

        await EntityResolutionStep().run(context)

        assert names(context) == []
        assert llm.prompts == [], "an off-tier mention must not cost a model call"
        assert suppressed(context, SuppressionReason.ENTITY_OFF_GRANULARITY) == 1
        assert context.research.statistics["entity_mentions_off_granularity"] == 1

    async def test_a_surface_form_that_names_no_place_is_not_merged(self) -> None:
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("my ex's cabin", None, 0.0)])])
        context = context_with(counted=[analysis("c1", mention("my ex's cabin"))], llm=llm)

        await EntityResolutionStep().run(context)

        assert names(context) == []
        assert suppressed(context, SuppressionReason.ENTITY_UNRESOLVED) == 1

    async def test_an_unrelated_mention_does_not_disturb_the_ones_around_it(self) -> None:
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("my ex's cabin", None, 0.0)])])
        context = context_with(
            counted=[analysis("c1", mention("Alaska"), mention("my ex's cabin"))], llm=llm
        )

        await EntityResolutionStep().run(context)

        assert resolved_names(context) == ["Alaska"]


class TestTheModelProposesNamesNotMerges:
    async def test_only_unsettled_forms_are_put_to_the_model(self) -> None:
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("the Mitten", "Michigan", 0.9)])])
        context = context_with(
            counted=[analysis("c1", mention("Alaska"), mention("the Mitten"))], llm=llm
        )

        await EntityResolutionStep().run(context)

        assert "the Mitten" in llm.prompts[0]
        assert "surface_form: Alaska" not in llm.prompts[0]

    async def test_a_confident_answer_merges_into_the_catalog_entity(self) -> None:
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("the Mitten", "Michigan", 0.9)])])
        context = context_with(
            counted=[analysis("c1", mention("the Mitten")), analysis("c2", mention("Michigan"))],
            llm=llm,
        )

        await EntityResolutionStep().run(context)

        assert names(context) == ["Michigan"]
        assert context.data["entities"][0].canonical_id == "state:michigan"

    async def test_a_place_the_catalog_does_not_hold_becomes_a_new_entity(self) -> None:
        """The catalogue covers states; a query about islands has to build its own."""
        llm = RecordingLLM(
            [EntityResolutionBatch(items=[answer("Fuerte", "Fuerteventura", 0.9)])]
        )
        context = context_with(
            counted=[analysis("c1", mention("Fuerte", entity_type=EntityType.ISLAND))],
            llm=llm,
            granularity=EntityType.ISLAND,
        )

        await EntityResolutionStep().run(context)

        assert names(context) == ["Fuerteventura"]
        assert context.data["entities"][0].canonical_id == "island:fuerteventura"
        assert "held as a new entity" in outcome(context, "Fuerte").reason

    async def test_an_answer_below_the_confidence_threshold_is_not_merged(self) -> None:
        """`PROJECT.md` §15: never silently merge when confidence is too low."""
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("the Mitten", "Michigan", 0.5)])])
        context = context_with(counted=[analysis("c1", mention("the Mitten"))], llm=llm)

        await EntityResolutionStep().run(context)

        assert names(context) == []
        assert "below 0.70; not merged" in outcome(context, "the Mitten").reason
        assert suppressed(context, SuppressionReason.ENTITY_UNRESOLVED) == 1

    async def test_the_confidence_threshold_is_configuration(self) -> None:
        config = ResearchConfig(entity_resolution=EntityResolutionConfig(confidence_threshold=0.4))
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("the Mitten", "Michigan", 0.5)])])
        context = context_with(
            counted=[analysis("c1", mention("the Mitten"))], llm=llm, config=config
        )

        await EntityResolutionStep().run(context)

        assert names(context) == ["Michigan"]

    async def test_an_answer_for_a_form_we_never_asked_about_is_discarded(self) -> None:
        llm = RecordingLLM(
            [
                EntityResolutionBatch(
                    items=[answer("the Mitten", "Michigan", 0.9), answer("Narnia", "Narnia", 0.9)]
                )
            ]
        )
        context = context_with(counted=[analysis("c1", mention("the Mitten"))], llm=llm)

        await EntityResolutionStep().run(context)

        assert names(context) == ["Michigan"]
        assert context.research.statistics["entity_resolution_items_discarded"] == 1

    async def test_a_form_the_model_skipped_is_recorded_as_unanswered(self) -> None:
        """Silence is not a resolution — and not an absence of opinion either."""
        llm = RecordingLLM([EntityResolutionBatch(items=[])])
        context = context_with(counted=[analysis("c1", mention("the Mitten"))], llm=llm)

        await EntityResolutionStep().run(context)

        assert names(context) == []
        assert suppressed(context, SuppressionReason.ENTITY_RESOLUTION_NO_RESULT) == 1

    async def test_forms_are_asked_about_in_bounded_batches(self) -> None:
        forms = [f"nickname {index}" for index in range(5)]
        llm = RecordingLLM(
            [
                EntityResolutionBatch(items=[answer(form, None, 0.1) for form in forms[:2]]),
                EntityResolutionBatch(items=[answer(form, None, 0.1) for form in forms[2:4]]),
                EntityResolutionBatch(items=[answer(forms[4], None, 0.1)]),
            ]
        )
        context = context_with(
            counted=[analysis("c1", *(mention(form) for form in forms))], llm=llm
        )

        await EntityResolutionStep(batch_size=2).run(context)

        assert len(llm.prompts) == 3

    async def test_one_question_per_distinct_form_however_many_mentions_use_it(self) -> None:
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("the Mitten", "Michigan", 0.9)])])
        context = context_with(
            counted=[analysis(f"c{index}", mention("the Mitten")) for index in range(20)], llm=llm
        )

        await EntityResolutionStep().run(context)

        assert len(llm.prompts) == 1
        assert len(context.data["counted_resolutions"]) == 20


class TestAccounting:
    async def test_every_surface_form_is_recorded_with_its_occurrence_count(self) -> None:
        context = context_with(
            counted=[
                analysis("c1", mention("Alaska")),
                analysis("c2", mention("Alaska")),
                analysis("c3", mention("AK")),
            ]
        )

        await EntityResolutionStep().run(context)

        assert outcome(context, "Alaska").occurrences == 2
        assert outcome(context, "AK").occurrences == 1

    async def test_the_counted_and_evidence_corpora_stay_apart(self) -> None:
        """§4.5's binding rule survives the step, as it did through analysis."""
        context = context_with(
            counted=[analysis("c1", mention("Alaska"))],
            evidence=[analysis("c2", mention("Oregon"))],
        )

        await EntityResolutionStep().run(context)

        assert resolved_names(context, "counted_resolutions") == ["Alaska"]
        assert resolved_names(context, "evidence_resolutions") == ["Oregon"]
        assert len(context.data["resolved_mentions"]) == 2

    async def test_statistics_account_for_every_mention(self) -> None:
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("my ex's cabin", None, 0.0)])])
        context = context_with(
            counted=[
                analysis("c1", mention("Alaska"), mention("my ex's cabin")),
                analysis("c2", mention("Denali", entity_type=EntityType.PARK)),
            ],
            llm=llm,
        )

        await EntityResolutionStep().run(context)

        statistics = context.research.statistics
        assert statistics["entity_mentions_total"] == 3
        assert statistics["entity_mentions_resolved"] == 1
        assert statistics["entity_mentions_unresolved"] == 1
        assert statistics["entity_mentions_off_granularity"] == 1
        assert statistics["entities_resolved"] == 1
        assert statistics["entity_forms_resolved_by_rule"] == 1
        assert statistics["entity_forms_unresolved"] == 2

    async def test_an_empty_corpus_resolves_to_nothing_without_asking(self) -> None:
        llm = RecordingLLM()
        context = context_with(llm=llm)

        await EntityResolutionStep().run(context)

        assert llm.prompts == []
        assert context.data["entities"] == []
        assert context.research.statistics["entity_mentions_total"] == 0

    async def test_the_same_corpus_resolves_identically_twice(self) -> None:
        """Identical input, identical ids — the property ranking's tiebreak needs."""
        analyses = [analysis("c1", mention("Alaska")), analysis("c2", mention("AK"))]
        runs = []
        for _ in range(2):
            context = context_with(counted=list(analyses))
            await EntityResolutionStep().run(context)
            runs.append([entity.canonical_id for entity in context.data["entities"]])

        assert runs[0] == runs[1] == ["state:alaska"]


class TestSuppressedRunsAreDistinguishable:
    """Plan §0.1's regression: a run that lost its names must not look thin."""

    async def _thin(self) -> PipelineContext:
        """One comment, one name, resolved. Genuinely little was said."""
        context = context_with(counted=[analysis("c1", mention("Alaska"))])
        await EntityResolutionStep().run(context)
        return context

    async def _suppressed(self) -> PipelineContext:
        """Ten comments naming a place the run could not identify at all."""
        llm = RecordingLLM([EntityResolutionBatch(items=[answer("that one state", None, 0.1)])])
        context = context_with(
            counted=[analysis(f"c{index}", mention("that one state")) for index in range(10)],
            llm=llm,
        )
        await EntityResolutionStep().run(context)
        return context

    async def test_both_runs_produce_few_entities(self) -> None:
        """The trap: on the number alone, these two are indistinguishable."""
        assert len(names(await self._thin())) <= 1
        assert len(names(await self._suppressed())) == 0

    async def test_only_the_suppressed_run_reports_suppressions(self) -> None:
        thin = await self._thin()
        suppressed_run = await self._suppressed()

        assert thin.research.diagnostics.suppressions == []
        assert suppressed(suppressed_run, SuppressionReason.ENTITY_UNRESOLVED) == 10

    async def test_the_suppressed_run_names_the_form_it_could_not_place(self) -> None:
        suppressed_run = await self._suppressed()

        entry = outcome(suppressed_run, "that one state")
        assert entry.entity_id is None
        assert entry.occurrences == 10
        assert entry.reason

    async def test_their_statistics_differ(self) -> None:
        thin = (await self._thin()).research.statistics
        suppressed_run = (await self._suppressed()).research.statistics

        assert thin["entity_mentions_unresolved"] == 0
        assert suppressed_run["entity_mentions_unresolved"] == 10
        assert thin["entity_mentions_resolved"] == 1
        assert suppressed_run["entity_mentions_resolved"] == 0

    async def test_the_diagnostics_survive_serialization(self) -> None:
        """They reach the API through the research snapshot (plan §0.1 rule 2)."""
        suppressed_run = await self._suppressed()

        dumped = suppressed_run.research.model_dump(mode="json")
        recorded = dumped["diagnostics"]["entity_resolutions"]
        assert [entry["surface_form"] for entry in recorded] == ["that one state"]
        assert recorded[0]["entity_id"] is None


class TestPlanContract:
    def test_the_step_satisfies_the_pipeline_step_protocol(self) -> None:
        from tripfinder.pipeline.base import PipelineStep

        assert isinstance(EntityResolutionStep(), PipelineStep)

    async def test_a_missing_plan_is_an_error_rather_than_a_silent_empty_run(self) -> None:
        context = make_context(status=ResearchStatus.ANALYZING)
        del context.data["plan"]

        with pytest.raises(KeyError):
            await EntityResolutionStep().run(context)
