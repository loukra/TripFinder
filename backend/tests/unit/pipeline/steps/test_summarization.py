"""Result Summarization (plan §4.6 step 13, `PROJECT.md` Phase 12).

Covers the phase's acceptance criteria in order: a grounded explanation is
attached to its result; missing evidence never triggers a call and never
invents an explanation; a cited quote that was not actually given to the
model discards the whole explanation (the hallucination safeguard); and an
answer that cannot be matched to a requested entity is dropped rather than
coerced.

The closing class is plan §0.1's pair: a suppressed explanation and a
missing one must look different in the diagnostics, even though both
results end up with no explanation at all.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from builders.phase7 import make_context
from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.analysis.comment_analysis import EntityMention
from tripfinder.analysis.entity_resolution import ResolvedMention
from tripfinder.analysis.summarization import EntitySummary, EntitySummaryBatch
from tripfinder.domain.models import Entity, EntityType, Result, Stance, SuppressionReason
from tripfinder.domain.ports import LLMProvider
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.summarization import SummarizationStep

ALASKA = Entity(canonical_id="state:alaska", canonical_name="Alaska", entity_type=EntityType.STATE)
OREGON = Entity(canonical_id="state:oregon", canonical_name="Oregon", entity_type=EntityType.STATE)

QUOTE = "Alaska has some of the most spectacular untouched wilderness in America."


class RecordingLLM:
    """Wraps the fake provider and keeps every prompt it was asked to answer."""

    def __init__(self, responses: Sequence[EntitySummaryBatch]) -> None:
        self._inner = FakeLLMProvider({EntitySummaryBatch: list(responses)})
        self.prompts: list[str] = []

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        self.prompts.append(prompt)
        return await self._inner.complete_structured(prompt=prompt, response_model=response_model)


class NoCallLLM:
    """Fails the test the moment a call is made — proves the step made none."""

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        raise AssertionError("no LLM call should have been made")


def _result(entity: Entity, *, supporter_count: int = 5) -> Result:
    return Result(
        entity_id=entity.canonical_id,
        entity_name=entity.canonical_name,
        supporter_count=supporter_count,
        share=1.0,
        respondent_pool_size=supporter_count,
        discussion_count=1,
        weighted_score=float(supporter_count),
        confidence=0.8,
    )


def _resolution(
    entity: Entity,
    *,
    quote: str = QUOTE,
    stance: Stance = Stance.POSITIVE,
    comment_id: str = "c1",
) -> ResolvedMention:
    return ResolvedMention(
        comment_id=comment_id,
        mention=EntityMention(
            raw_text=entity.canonical_name,
            entity_type=entity.entity_type,
            stance=stance,
            strength=0.8,
            supporting_quote=quote,
        ),
        entity=entity,
    )


def _summary(
    entity: Entity,
    *,
    explanation: str = "Travelers love its wilderness.",
    cited_quotes: Sequence[str] = (QUOTE,),
) -> EntitySummary:
    return EntitySummary(
        entity_id=entity.canonical_id, explanation=explanation, cited_quotes=list(cited_quotes)
    )


def _context(
    *,
    results: Sequence[Result],
    resolutions: Sequence[ResolvedMention] = (),
    llm: LLMProvider | None = None,
) -> PipelineContext:
    context = make_context(llm=llm or FakeLLMProvider())
    context.research.results = list(results)
    context.data["counted_resolutions"] = list(resolutions)
    return context


def _suppressions(context: PipelineContext, reason: SuppressionReason) -> list[int]:
    return [
        entry.count
        for entry in context.research.diagnostics.suppressions
        if entry.reason is reason
    ]


class TestAGroundedExplanationIsAttached:
    async def test_the_result_gets_its_explanation(self) -> None:
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA)],
            llm=RecordingLLM([EntitySummaryBatch(items=[_summary(ALASKA)])]),
        )

        await SummarizationStep().run(context)

        [result] = context.research.results
        assert result.explanation == "Travelers love its wilderness."
        assert context.research.statistics["results_explained"] == 1
        assert context.research.diagnostics.suppressions == []

    async def test_the_prompt_carries_the_entitys_quotes(self) -> None:
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA)],
            llm=RecordingLLM([EntitySummaryBatch(items=[_summary(ALASKA)])]),
        )

        await SummarizationStep().run(context)

        llm = context.llm
        assert isinstance(llm, RecordingLLM)
        assert QUOTE in llm.prompts[0]
        assert "Alaska" in llm.prompts[0]


class TestMissingEvidence:
    async def test_an_entity_with_no_stored_quotes_gets_no_call_and_no_explanation(self) -> None:
        context = _context(results=[_result(ALASKA)], resolutions=[], llm=NoCallLLM())

        await SummarizationStep().run(context)

        [result] = context.research.results
        assert result.explanation is None
        assert _suppressions(context, SuppressionReason.SUMMARIZATION_NO_EVIDENCE) == [1]
        assert context.research.statistics["results_without_evidence"] == 1

    async def test_only_positive_stance_mentions_count_as_evidence(self) -> None:
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA, stance=Stance.NEGATIVE)],
            llm=NoCallLLM(),
        )

        await SummarizationStep().run(context)

        [result] = context.research.results
        assert result.explanation is None
        assert _suppressions(context, SuppressionReason.SUMMARIZATION_NO_EVIDENCE) == [1]

    async def test_no_results_means_no_call_at_all(self) -> None:
        context = _context(results=[], llm=NoCallLLM())

        await SummarizationStep().run(context)

        assert context.research.statistics["results_explained"] == 0


class TestHallucinationSafeguard:
    """`PROJECT.md` §29: a quote that was never given is not evidence."""

    async def test_a_fabricated_cited_quote_discards_the_explanation(self) -> None:
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA)],
            llm=RecordingLLM(
                [EntitySummaryBatch(items=[_summary(ALASKA, cited_quotes=("invented quote",))])]
            ),
        )

        await SummarizationStep().run(context)

        [result] = context.research.results
        assert result.explanation is None
        assert _suppressions(context, SuppressionReason.SUMMARIZATION_FABRICATED_QUOTE) == [1]

    async def test_a_requoted_line_break_is_not_a_fabrication(self) -> None:
        """The rule is about the words, not the line breaks between them.

        A comment quoted across two paragraphs comes back from the model
        re-wrapped. Reporting that as a fabricated quote suppressed every
        explanation in a real run — five of five — while the quotes were
        the ones we had handed it, character for character apart from a
        newline."""
        stored = "The lakes are unreal.\n\n  Nobody goes in autumn."
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA, quote=stored)],
            llm=RecordingLLM(
                [
                    EntitySummaryBatch(
                        items=[
                            _summary(
                                ALASKA,
                                cited_quotes=("The lakes are unreal. Nobody goes in autumn.",),
                            )
                        ]
                    )
                ]
            ),
        )

        await SummarizationStep().run(context)

        [result] = context.research.results
        assert result.explanation is not None
        assert _suppressions(context, SuppressionReason.SUMMARIZATION_FABRICATED_QUOTE) == []

    async def test_a_quote_copied_with_its_wrapping_marks_is_not_a_fabrication(self) -> None:
        """The second time this check fired on its own formatting.

        The prompt printed every supplied quote inside quotation marks and
        told the model to copy it character for character; the model copied
        the marks too. A measured run reported five fabrications, lost all
        five explanations, and every cited quote was one we had handed it."""
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA)],
            llm=RecordingLLM(
                [EntitySummaryBatch(items=[_summary(ALASKA, cited_quotes=(f'"{QUOTE}"',))])]
            ),
        )

        await SummarizationStep().run(context)

        [result] = context.research.results
        assert result.explanation is not None
        assert _suppressions(context, SuppressionReason.SUMMARIZATION_FABRICATED_QUOTE) == []

    async def test_curly_wrapping_marks_are_stripped_too(self) -> None:
        """Models render the pair either way, and which one arrived says
        nothing about whether the words are ours."""
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA)],
            llm=RecordingLLM(
                [
                    EntitySummaryBatch(
                        items=[_summary(ALASKA, cited_quotes=(f"\u201c{QUOTE}\u201d",))]
                    )
                ]
            ),
        )

        await SummarizationStep().run(context)

        assert context.research.results[0].explanation is not None

    async def test_an_inner_quotation_mark_is_still_part_of_the_quote(self) -> None:
        """Only a *matched enclosing* pair is a delimiter. A quotation mark
        inside the text is one of the words, and dropping it would let a
        citation differ from what was supplied."""
        stored = 'He said "go north" and he was right'
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA, quote=stored)],
            llm=RecordingLLM(
                [
                    EntitySummaryBatch(
                        items=[
                            _summary(
                                ALASKA, cited_quotes=("He said go north and he was right",)
                            )
                        ]
                    )
                ]
            ),
        )

        await SummarizationStep().run(context)

        assert context.research.results[0].explanation is None
        assert _suppressions(context, SuppressionReason.SUMMARIZATION_FABRICATED_QUOTE) == [1]

    async def test_a_trimmed_span_of_a_supplied_quote_is_still_refused(self) -> None:
        """Unwrapping a delimiter is not the same as accepting a fragment.
        The rule stays "the quotes we handed it", whole."""
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA)],
            llm=RecordingLLM(
                [EntitySummaryBatch(items=[_summary(ALASKA, cited_quotes=(QUOTE[:12],))])]
            ),
        )

        await SummarizationStep().run(context)

        assert context.research.results[0].explanation is None

    async def test_an_explanation_citing_no_quotes_is_ungrounded(self) -> None:
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA)],
            llm=RecordingLLM([EntitySummaryBatch(items=[_summary(ALASKA, cited_quotes=())])]),
        )

        await SummarizationStep().run(context)

        [result] = context.research.results
        assert result.explanation is None
        assert _suppressions(context, SuppressionReason.SUMMARIZATION_FABRICATED_QUOTE) == [1]

    async def test_verification_is_exact_rather_than_approximate(self) -> None:
        tidied = QUOTE.replace("has", "has,")
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA)],
            llm=RecordingLLM(
                [EntitySummaryBatch(items=[_summary(ALASKA, cited_quotes=(tidied,))])]
            ),
        )

        await SummarizationStep().run(context)

        assert context.research.results[0].explanation is None


class TestAnAnswerThatCannotBeMatchedIsDropped:
    async def test_an_item_for_an_entity_never_asked_about_is_discarded(self) -> None:
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA)],
            llm=RecordingLLM(
                [EntitySummaryBatch(items=[_summary(ALASKA), _summary(OREGON)])]
            ),
        )

        await SummarizationStep().run(context)

        assert context.research.statistics["summarization_items_discarded"] == 1
        assert context.research.results[0].explanation is not None

    async def test_a_duplicate_item_for_one_entity_is_discarded(self) -> None:
        context = _context(
            results=[_result(ALASKA)],
            resolutions=[_resolution(ALASKA)],
            llm=RecordingLLM(
                [
                    EntitySummaryBatch(
                        items=[_summary(ALASKA), _summary(ALASKA, explanation="second")]
                    )
                ]
            ),
        )

        await SummarizationStep().run(context)

        [result] = context.research.results
        assert result.explanation == "Travelers love its wilderness."
        assert context.research.statistics["summarization_items_discarded"] == 1

    async def test_an_entity_the_model_skipped_is_recorded_as_missing(self) -> None:
        oregon_quote = "Oregon's coast is unreal and empty most of the year."
        context = _context(
            results=[_result(ALASKA), _result(OREGON)],
            resolutions=[_resolution(ALASKA), _resolution(OREGON, quote=oregon_quote)],
            llm=RecordingLLM([EntitySummaryBatch(items=[_summary(ALASKA)])]),
        )

        await SummarizationStep().run(context)

        oregon = next(r for r in context.research.results if r.entity_id == OREGON.canonical_id)
        assert oregon.explanation is None
        assert _suppressions(context, SuppressionReason.SUMMARIZATION_NO_RESULT) == [1]


class TestEvidenceIsCappedAndDeduplicated:
    async def test_quotes_beyond_the_cap_are_not_sent(self) -> None:
        quotes = [f"Unique alaska memory {i} full of glaciers and calm skies" for i in range(5)]
        resolutions = [
            _resolution(ALASKA, quote=quote, comment_id=f"c{i}")
            for i, quote in enumerate(quotes)
        ]
        context = _context(
            results=[_result(ALASKA)],
            resolutions=resolutions,
            llm=RecordingLLM(
                [EntitySummaryBatch(items=[_summary(ALASKA, cited_quotes=(quotes[0],))])]
            ),
        )

        await SummarizationStep(max_quotes_per_entity=2).run(context)

        llm = context.llm
        assert isinstance(llm, RecordingLLM)
        assert llm.prompts[0].count("    [") == 2

    async def test_a_repeated_quote_is_sent_once(self) -> None:
        resolutions = [
            _resolution(ALASKA, comment_id="c1"),
            _resolution(ALASKA, comment_id="c2"),
        ]
        context = _context(
            results=[_result(ALASKA)],
            resolutions=resolutions,
            llm=RecordingLLM([EntitySummaryBatch(items=[_summary(ALASKA)])]),
        )

        await SummarizationStep().run(context)

        llm = context.llm
        assert isinstance(llm, RecordingLLM)
        assert llm.prompts[0].count("    [") == 1


class TestBatching:
    async def test_entities_are_sent_in_batches_of_the_configured_size(self) -> None:
        entities = [
            Entity(
                canonical_id=f"state:s{i}",
                canonical_name=f"State{i}",
                entity_type=EntityType.STATE,
            )
            for i in range(4)
        ]
        resolutions = [
            _resolution(entity, quote=f"State{i} is quietly the best-kept secret in the region")
            for i, entity in enumerate(entities)
        ]
        results = [_result(entity) for entity in entities]
        pairs = list(zip(entities, resolutions, strict=True))
        responses = [
            EntitySummaryBatch(
                items=[
                    _summary(entity, cited_quotes=(resolution.mention.supporting_quote,))
                    for entity, resolution in batch
                ]
            )
            for batch in (pairs[:2], pairs[2:])
        ]
        context = _context(results=results, resolutions=resolutions, llm=RecordingLLM(responses))

        await SummarizationStep(batch_size=2).run(context)

        llm = context.llm
        assert isinstance(llm, RecordingLLM)
        assert len(llm.prompts) == 2
        assert all(result.explanation is not None for result in context.research.results)


class TestASuppressedExplanationIsDistinguishableFromAMissingOne:
    """The §0.1 rule-5 test for this step.

    Both results end with no explanation. Only one of them had evidence and
    lost it to the hallucination safeguard; the diagnostics have to say
    which.
    """

    @staticmethod
    async def _run() -> PipelineContext:
        context = _context(
            results=[_result(ALASKA), _result(OREGON)],
            resolutions=[_resolution(ALASKA)],  # Oregon has no stored evidence at all
            llm=RecordingLLM(
                [EntitySummaryBatch(items=[_summary(ALASKA, cited_quotes=("invented",))])]
            ),
        )
        await SummarizationStep().run(context)
        return context

    async def test_both_results_end_with_no_explanation(self) -> None:
        context = await self._run()

        alaska, oregon = context.research.results
        assert alaska.explanation is None
        assert oregon.explanation is None

    async def test_the_diagnostics_tell_the_two_apart(self) -> None:
        context = await self._run()

        assert _suppressions(context, SuppressionReason.SUMMARIZATION_NO_EVIDENCE) == [1]
        assert _suppressions(context, SuppressionReason.SUMMARIZATION_FABRICATED_QUOTE) == [1]

    async def test_the_statistics_tell_the_two_apart_too(self) -> None:
        context = await self._run()

        assert context.research.statistics["results_without_evidence"] == 1
        assert context.research.statistics["summarization_fabricated_quote"] == 1
        assert context.research.statistics["results_explained"] == 0
