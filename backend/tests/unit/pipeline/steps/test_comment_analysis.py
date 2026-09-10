"""Comment Analysis (plan §4.6 step 7, §5).

The acceptance criteria covered here, in plan order: the labeled fixture set
drives every case; a comment that recommends a place in none of the query's
words survives with its mention intact, where keyword matching would have
dropped it; and quote verification discards a fabricated span.

The §0.1 pair — a run whose evidence was thrown away must not look like a
run that found little — closes the file.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import BaseModel

from builders.labeled_comments import (
    LabeledComment,
    expected_batch,
    labeled,
    labeled_comments,
    one,
)
from builders.phase7 import make_context
from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.analysis.comment_analysis import (
    CommentAnalysis,
    CommentAnalysisBatch,
    EntityMention,
)
from tripfinder.domain.models import (
    Comment,
    EntityType,
    ResearchStatus,
    Stance,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.comment_analysis import CommentAnalysisStep

ALL = labeled_comments()


class RecordingLLM:
    """Wraps the fake provider and keeps every prompt it was asked to answer."""

    def __init__(self, responses: Sequence[CommentAnalysisBatch]) -> None:
        self._inner = FakeLLMProvider({CommentAnalysisBatch: list(responses)})
        self.prompts: list[str] = []

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        self.prompts.append(prompt)
        return await self._inner.complete_structured(prompt=prompt, response_model=response_model)


def _context(
    *,
    counted: Sequence[LabeledComment] = (),
    evidence: Sequence[LabeledComment] = (),
    responses: Sequence[CommentAnalysisBatch],
) -> PipelineContext:
    context = make_context(llm=RecordingLLM(responses), status=ResearchStatus.ANALYZING)
    context.data["counted_comments"] = [entry.as_comment() for entry in counted]
    context.data["evidence_comments"] = [
        entry.as_comment(document_id="d-topical") for entry in evidence
    ]
    return context


def _suppressions(context: PipelineContext, reason: SuppressionReason) -> list[int]:
    return [
        entry.count
        for entry in context.research.diagnostics.suppressions
        if entry.reason is reason
    ]


def _mention(**overrides: object) -> EntityMention:
    payload: dict[str, object] = {
        "raw_text": "Michigan",
        "normalized_guess": "Michigan",
        "entity_type": EntityType.STATE,
        "stance": Stance.POSITIVE,
        "strength": 0.8,
        "supporting_quote": "Michigan is hands down the most underrated state for nature",
    }
    payload.update(overrides)
    return EntityMention.model_validate(payload)


def _analysis(comment_id: str, *mentions: EntityMention) -> CommentAnalysis:
    return CommentAnalysis(
        comment_id=comment_id,
        topic_relevance=0.9,
        criterion_relevance=0.8,
        scope_match=True,
        overall_confidence=0.9,
        mentions=list(mentions),
        reasoning="a hand-built analysis",
    )


class TestTheWholeLabeledCorpus:
    async def test_every_comment_gets_an_analysis(self) -> None:
        context = _context(counted=ALL, responses=[expected_batch()])

        await CommentAnalysisStep().run(context)

        analysed = {analysis.comment_id for analysis in context.data["comment_analyses"]}
        assert analysed == {entry.id for entry in ALL}
        assert context.research.statistics["comments_with_analysis"] == len(ALL)

    async def test_an_irrelevant_comment_is_analysed_rather_than_dropped(self) -> None:
        """Relevance is a score to be recorded here, not a filter to apply (plan §4.1)."""
        irrelevant = labeled("irrelevant")
        context = _context(counted=irrelevant, responses=[expected_batch(irrelevant)])

        await CommentAnalysisStep().run(context)

        analyses = context.data["counted_analyses"]
        assert len(analyses) == len(irrelevant)
        assert all(analysis.topic_relevance < 0.5 for analysis in analyses)
        assert all(analysis.mentions == [] for analysis in analyses)

    async def test_an_ambiguous_comment_keeps_its_unusable_stance(self) -> None:
        """A mixed stance is evidence. §4.1 decides later that it is not a vote."""
        entry = one("c-ambiguous-1")
        context = _context(counted=[entry], responses=[expected_batch((entry,))])

        await CommentAnalysisStep().run(context)

        (analysis,) = context.data["counted_analyses"]
        assert [mention.stance for mention in analysis.mentions] == [Stance.MIXED]

    async def test_no_analysis_is_lost_or_invented(self) -> None:
        context = _context(counted=ALL, responses=[expected_batch()])

        await CommentAnalysisStep().run(context)

        statistics = context.research.statistics
        assert statistics["comments_without_analysis"] == 0
        assert statistics["analysis_items_discarded"] == 0
        assert statistics["analysis_mentions_fabricated_quote"] == 0
        assert context.research.diagnostics.suppressions == []


class TestSemanticMatchesSurviveWhereKeywordsWouldNot:
    """Plan §10 Phase 8 acceptance, asserted against our code rather than a model."""

    @pytest.mark.parametrize(
        "entry", labeled("equivalent_wording"), ids=lambda entry: str(entry.id)
    )
    async def test_a_recommendation_sharing_no_query_word_survives(
        self, entry: LabeledComment
    ) -> None:
        context = _context(counted=[entry], responses=[expected_batch((entry,))])

        await CommentAnalysisStep().run(context)

        (analysis,) = context.data["counted_analyses"]
        assert [mention.normalized_guess for mention in analysis.mentions] == [entry.entity]
        assert analysis.mentions[0].stance is Stance.POSITIVE

    async def test_the_state_it_recommends_is_never_named_in_its_body(self) -> None:
        """The mention exists because of meaning alone — the name is not in the text."""
        entry = one("c-equivalent-1")
        context = _context(counted=[entry], responses=[expected_batch((entry,))])

        await CommentAnalysisStep().run(context)

        (analysis,) = context.data["counted_analyses"]
        assert analysis.mentions[0].normalized_guess == "Oregon"
        assert "Oregon" not in entry.body
        assert analysis.mentions[0].raw_text in entry.body


class TestQuoteVerification:
    """`PROJECT.md` §29: a quote that is not in the comment is not evidence."""

    async def test_a_fabricated_quote_discards_its_mention(self) -> None:
        entry = one("c-clear-1")
        fabricated = _mention(supporting_quote="Michigan is the best state in the union")
        context = _context(
            counted=[entry],
            responses=[CommentAnalysisBatch(items=[_analysis(entry.id, fabricated)])],
        )

        await CommentAnalysisStep().run(context)

        (analysis,) = context.data["counted_analyses"]
        assert analysis.mentions == []

    async def test_the_analysis_itself_survives_a_fabricated_quote(self) -> None:
        """One bad mention costs its mention, not the comment's whole judgement."""
        entry = one("c-clear-1")
        context = _context(
            counted=[entry],
            responses=[
                CommentAnalysisBatch(
                    items=[
                        _analysis(
                            entry.id,
                            _mention(supporting_quote="not in the body at all"),
                            _mention(),
                        )
                    ]
                )
            ],
        )

        await CommentAnalysisStep().run(context)

        (analysis,) = context.data["counted_analyses"]
        assert [mention.supporting_quote for mention in analysis.mentions] == [
            _mention().supporting_quote
        ]

    async def test_a_fabricated_quote_is_counted_and_recorded(self) -> None:
        entry = one("c-clear-1")
        context = _context(
            counted=[entry],
            responses=[
                CommentAnalysisBatch(
                    items=[_analysis(entry.id, _mention(supporting_quote="invented"))]
                )
            ],
        )

        await CommentAnalysisStep().run(context)

        assert context.research.statistics["analysis_mentions_fabricated_quote"] == 1
        assert _suppressions(context, SuppressionReason.ANALYSIS_FABRICATED_QUOTE) == [1]

    async def test_verification_is_exact_rather_than_approximate(self) -> None:
        """A tidied-up quote is still a quote the commenter did not write."""
        entry = one("c-clear-1")
        tidied = _mention(supporting_quote="Michigan is hands-down the most underrated state")
        context = _context(
            counted=[entry], responses=[CommentAnalysisBatch(items=[_analysis(entry.id, tidied)])]
        )

        await CommentAnalysisStep().run(context)

        assert context.data["counted_analyses"][0].mentions == []


class TestBatching:
    async def test_comments_are_sent_in_batches_of_the_configured_size(self) -> None:
        context = _context(
            counted=ALL,
            responses=[expected_batch(ALL[:4]), expected_batch(ALL[4:8]), expected_batch(ALL[8:])],
        )

        await CommentAnalysisStep(batch_size=4).run(context)

        llm = context.llm
        assert isinstance(llm, RecordingLLM)
        assert len(llm.prompts) == 3
        assert len(context.data["comment_analyses"]) == len(ALL)

    async def test_a_prompt_carries_only_its_own_batch(self) -> None:
        context = _context(
            counted=ALL, responses=[expected_batch(ALL[:5]), expected_batch(ALL[5:])]
        )

        await CommentAnalysisStep(batch_size=5).run(context)

        llm = context.llm
        assert isinstance(llm, RecordingLLM)
        first, second = llm.prompts
        assert all(f"id={entry.id}" in first for entry in ALL[:5])
        assert all(f"id={entry.id}" not in first for entry in ALL[5:])
        assert all(f"id={entry.id}" in second for entry in ALL[5:])

    async def test_no_comments_means_no_call_at_all(self) -> None:
        context = _context(responses=[])

        await CommentAnalysisStep().run(context)

        llm = context.llm
        assert isinstance(llm, RecordingLLM)
        assert llm.prompts == []
        assert context.data["comment_analyses"] == []


class TestTheCountedAndEvidenceCorporaStaySeparate:
    """Plan §4.5: a topical thread's users may not reach the respondent pool."""

    async def test_analyses_keep_the_corpus_they_came_from(self) -> None:
        counted = labeled("clearly_relevant")
        evidence = labeled("ambiguous")
        context = _context(
            counted=counted,
            evidence=evidence,
            responses=[expected_batch(counted + evidence)],
        )

        await CommentAnalysisStep().run(context)

        assert [analysis.comment_id for analysis in context.data["counted_analyses"]] == [
            entry.id for entry in counted
        ]
        assert [analysis.comment_id for analysis in context.data["evidence_analyses"]] == [
            entry.id for entry in evidence
        ]

    async def test_the_counted_corpus_is_analysed_first(self) -> None:
        """Budget priority (plan §4.5): evidence spends only what is left."""
        counted = labeled("clearly_relevant")
        evidence = labeled("ambiguous")
        context = _context(
            counted=counted,
            evidence=evidence,
            responses=[expected_batch(counted), expected_batch(evidence)],
        )

        await CommentAnalysisStep(batch_size=len(counted)).run(context)

        llm = context.llm
        assert isinstance(llm, RecordingLLM)
        assert all(f"id={entry.id}" in llm.prompts[0] for entry in counted)


class TestAnAnswerThatCannotBeMatchedIsDropped:
    """Plan §5: invalid items are dropped with a logged reason, never coerced."""

    async def test_an_item_for_a_comment_we_never_sent_is_discarded(self) -> None:
        entry = one("c-clear-1")
        context = _context(
            counted=[entry],
            responses=[
                CommentAnalysisBatch(
                    items=[_analysis(entry.id, _mention()), _analysis("c-invented")]
                )
            ],
        )

        await CommentAnalysisStep().run(context)

        assert [analysis.comment_id for analysis in context.data["counted_analyses"]] == [entry.id]
        assert context.research.statistics["analysis_items_discarded"] == 1

    async def test_a_duplicate_item_for_one_comment_is_discarded(self) -> None:
        entry = one("c-clear-1")
        context = _context(
            counted=[entry],
            responses=[
                CommentAnalysisBatch(
                    items=[_analysis(entry.id, _mention()), _analysis(entry.id)]
                )
            ],
        )

        await CommentAnalysisStep().run(context)

        (analysis,) = context.data["counted_analyses"]
        assert len(analysis.mentions) == 1
        assert context.research.statistics["analysis_items_discarded"] == 1

    async def test_a_comment_the_model_skipped_is_recorded_as_suppressed(self) -> None:
        analysed, skipped = ALL[0], ALL[1]
        context = _context(
            counted=[analysed, skipped], responses=[expected_batch((analysed,))]
        )

        await CommentAnalysisStep().run(context)

        assert context.research.statistics["comments_without_analysis"] == 1
        assert _suppressions(context, SuppressionReason.ANALYSIS_NO_RESULT) == [1]


class TestASuppressedRunIsDistinguishableFromAThinOne:
    """The §0.1 rule-5 test for this step.

    Both runs end with zero usable mentions. Only one of them looked
    properly, and the diagnostics have to say which.
    """

    @staticmethod
    async def _thin_run() -> PipelineContext:
        """The model read every comment and found nothing recommended."""
        empty = CommentAnalysisBatch(
            items=[_analysis(entry.id) for entry in labeled("clearly_relevant")]
        )
        context = _context(counted=labeled("clearly_relevant"), responses=[empty])
        await CommentAnalysisStep().run(context)
        return context

    @staticmethod
    async def _suppressed_run() -> PipelineContext:
        """The model recommended plenty, and every quote was invented."""
        fabricated = CommentAnalysisBatch(
            items=[
                _analysis(entry.id, _mention(supporting_quote="never written by anyone"))
                for entry in labeled("clearly_relevant")
            ]
        )
        context = _context(counted=labeled("clearly_relevant"), responses=[fabricated])
        await CommentAnalysisStep().run(context)
        return context

    async def test_both_runs_end_with_no_usable_mentions(self) -> None:
        thin = await self._thin_run()
        suppressed = await self._suppressed_run()

        assert thin.research.statistics["analysis_mentions_extracted"] == 0
        assert suppressed.research.statistics["analysis_mentions_extracted"] == 0

    async def test_only_the_suppressed_run_reports_a_suppression(self) -> None:
        thin = await self._thin_run()
        suppressed = await self._suppressed_run()

        assert thin.research.diagnostics.suppressions == []
        assert _suppressions(suppressed, SuppressionReason.ANALYSIS_FABRICATED_QUOTE) == [2]

    async def test_the_suppression_names_what_it_dropped_and_why(self) -> None:
        suppressed = await self._suppressed_run()

        (entry,) = suppressed.research.diagnostics.suppressions
        assert entry.step == "comment_analysis"
        assert entry.detail is not None
        assert "quote" in entry.detail

    async def test_the_statistics_tell_the_two_apart(self) -> None:
        thin = await self._thin_run()
        suppressed = await self._suppressed_run()

        assert thin.research.statistics["analysis_mentions_fabricated_quote"] == 0
        assert suppressed.research.statistics["analysis_mentions_fabricated_quote"] == 2


class TestTheStepReadsWhatPreFilterWrote:
    async def test_comments_that_never_reached_pre_filter_are_not_analysed(self) -> None:
        """The step analyses the pre-filtered corpora, not ``comments``."""
        context = _context(responses=[])
        context.data["comments"] = [entry.as_comment() for entry in ALL]

        await CommentAnalysisStep().run(context)

        assert context.data["comment_analyses"] == []

    async def test_the_run_is_still_analysing_afterwards(self) -> None:
        """Steps 8-10 are analysis too; ``aggregating`` belongs to step 11 (plan §7)."""
        entry = one("c-clear-1")
        context = _context(counted=[entry], responses=[expected_batch((entry,))])

        await CommentAnalysisStep().run(context)

        assert context.research.status is ResearchStatus.ANALYZING


def test_the_fixture_comments_are_real_domain_comments() -> None:
    assert all(isinstance(entry.as_comment(), Comment) for entry in ALL)
