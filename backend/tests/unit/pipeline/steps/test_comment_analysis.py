"""Comment Analysis (plan §4.6 step 7, §5).

The acceptance criteria covered here, in plan order: the labeled fixture set
drives every case; a comment that recommends a place in none of the query's
words survives with its mention intact, where keyword matching would have
dropped it; and quote verification discards a fabricated span.

The §0.1 pair — a run whose evidence was thrown away must not look like a
run that found little — closes the file.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

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
from tripfinder.ai.errors import LLMCredentialError, LLMUnavailableError
from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.analysis.comment_analysis import (
    CommentAnalysis,
    CommentAnalysisBatch,
    EntityMention,
)
from tripfinder.domain.config import SourceHealthFloors
from tripfinder.domain.models import (
    EntityType,
    FailureKind,
    ReasonCode,
    ResearchFlag,
    ResearchStatus,
    SourceOutcome,
    Stance,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.deadline import admission_deadline, mark_started
from tripfinder.pipeline.health import SourceAssessment, get_recorder
from tripfinder.pipeline.steps.comment_analysis import (
    ANALYSIS_ADAPTER,
    DEFAULT_MAX_CONCURRENT_BATCHES,
    CommentAnalysisStep,
)

ALL = labeled_comments()
CLEAR = labeled("clearly_relevant")


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


START = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


class Clock:
    """A clock that advances by a fixed step every time a call is made.

    Wall-clock sleeping would make these tests slow and flaky; what the
    admission gate actually reads is "how much time has passed", so the
    tests drive that directly.
    """

    def __init__(self, start: datetime, *, per_call: timedelta) -> None:
        self._now = start
        self._per_call = per_call
        self.calls = 0

    def read(self) -> datetime:
        return self._now

    def spend(self) -> None:
        self.calls += 1
        self._now += self._per_call


class SlowLLM:
    """Answers in order, and charges the clock for each call it serves."""

    def __init__(self, answers: Sequence[CommentAnalysisBatch], *, clock: Clock) -> None:
        self._answers = list(answers)
        self._clock = clock
        self._next = 0

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        answer = self._answers[self._next]
        self._next += 1
        await asyncio.sleep(0)
        self._clock.spend()
        assert isinstance(answer, response_model)
        return answer


class FlakyLLM:
    """Answers each batch in order — or raises, where a failure was scripted."""

    def __init__(self, answers: Sequence[CommentAnalysisBatch | Exception]) -> None:
        self._answers = list(answers)
        self._next = 0

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        answer = self._answers[self._next]
        self._next += 1
        await asyncio.sleep(0)
        if isinstance(answer, Exception):
            raise answer
        assert isinstance(answer, response_model)
        return answer


def _healthy_assessment() -> SourceAssessment:
    """What §8.1's health step would have recorded before analysis began."""
    return SourceAssessment(
        outcome=SourceOutcome.HEALTHY,
        aggregate_success_rate=1.0,
        posts_retrieved=25,
        comments_analyzed=len(ALL),
    )


class ConcurrencyWatchingLLM:
    """Answers like the fake, and records how many calls overlapped.

    Every call yields control at least once before answering, so a step that
    dispatches sequentially cannot accidentally look concurrent: with an
    ``await`` in the middle, overlap is observable exactly when it is real.
    """

    def __init__(self, responses: Sequence[CommentAnalysisBatch]) -> None:
        self._inner = FakeLLMProvider({CommentAnalysisBatch: list(responses)})
        self.in_flight = 0
        self.peak_in_flight = 0

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)
            return await self._inner.complete_structured(
                prompt=prompt, response_model=response_model
            )
        finally:
            self.in_flight -= 1


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
        reason_code=ReasonCode.RECOMMENDS,
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

        assert entry.mention is not None
        (analysis,) = context.data["counted_analyses"]
        assert [mention.raw_text for mention in analysis.mentions] == [entry.mention.raw_text]
        assert analysis.mentions[0].stance is Stance.POSITIVE

    async def test_the_state_it_recommends_is_never_named_in_its_body(self) -> None:
        """The mention exists because of meaning alone — the name is not in the text.

        What this step reports is the *wording*: "the Beaver State". Arriving
        at Oregon from it is §4.6 step 8's job, and since 14.6a it is the only
        step that does so — the model no longer ships a canonical guess of its
        own alongside the quote.
        """
        entry = one("c-equivalent-1")
        context = _context(counted=[entry], responses=[expected_batch((entry,))])

        await CommentAnalysisStep().run(context)

        (analysis,) = context.data["counted_analyses"]
        assert analysis.mentions[0].raw_text == "Beaver State"
        assert analysis.mentions[0].raw_text in entry.body
        assert "Oregon" not in entry.body


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


class TestTheReasonCodeBreakdown:
    """§2.12 traded a prose sentence for a countable one (plan §0.1)."""

    async def test_every_code_is_reported_even_at_zero(self) -> None:
        """A code missing from the breakdown and a code at zero read alike."""
        context = _context(counted=CLEAR, responses=[expected_batch(CLEAR)])

        await CommentAnalysisStep().run(context)

        statistics = context.research.statistics
        assert all(f"analysis_reason_{code.value}" in statistics for code in ReasonCode)

    async def test_the_counts_add_up_to_the_comments_analysed(self) -> None:
        context = _context(counted=ALL, responses=[expected_batch()])

        await CommentAnalysisStep().run(context)

        statistics = context.research.statistics
        total = sum(statistics[f"analysis_reason_{code.value}"] for code in ReasonCode)
        assert total == statistics["comments_with_analysis"]

    async def test_an_off_topic_corpus_and_a_recommending_one_are_distinguishable(self) -> None:
        """The whole point: "nobody recommended anything" has to name its shape."""
        irrelevant = labeled("irrelevant")
        off_topic = _context(counted=irrelevant, responses=[expected_batch(irrelevant)])
        recommending = _context(counted=CLEAR, responses=[expected_batch(CLEAR)])

        await CommentAnalysisStep().run(off_topic)
        await CommentAnalysisStep().run(recommending)

        assert off_topic.research.statistics["analysis_reason_off_topic"] == len(irrelevant)
        assert off_topic.research.statistics["analysis_reason_recommends"] == 0
        assert recommending.research.statistics["analysis_reason_recommends"] == len(CLEAR)
        assert recommending.research.statistics["analysis_reason_off_topic"] == 0


class TestBatchesRunConcurrently:
    """Plan §2.12/14.6b: 50 round trips in series were 93 % of a 2408 s run."""

    def _watching(self, entries: Sequence[LabeledComment], *, batch_size: int) -> PipelineContext:
        batches = [
            tuple(entries[start : start + batch_size])
            for start in range(0, len(entries), batch_size)
        ]
        context = make_context(
            llm=ConcurrencyWatchingLLM([expected_batch(batch) for batch in batches]),
            status=ResearchStatus.ANALYZING,
        )
        context.data["counted_comments"] = [entry.as_comment() for entry in entries]
        context.data["evidence_comments"] = []
        return context

    async def test_more_than_one_batch_is_in_flight_at_a_time(self) -> None:
        context = self._watching(ALL, batch_size=2)

        await CommentAnalysisStep(batch_size=2, max_concurrent_batches=5).run(context)

        llm = context.llm
        assert isinstance(llm, ConcurrencyWatchingLLM)
        assert llm.peak_in_flight > 1

    async def test_the_ceiling_is_never_exceeded(self) -> None:
        """Unbounded fan-out buys 429s, which §8.1 has to report as lost evidence."""
        context = self._watching(ALL, batch_size=1)

        await CommentAnalysisStep(batch_size=1, max_concurrent_batches=3).run(context)

        llm = context.llm
        assert isinstance(llm, ConcurrencyWatchingLLM)
        assert llm.peak_in_flight == 3
        assert len(context.data["comment_analyses"]) == len(ALL)

    async def test_a_ceiling_of_one_is_still_sequential(self) -> None:
        context = self._watching(ALL, batch_size=1)

        await CommentAnalysisStep(batch_size=1, max_concurrent_batches=1).run(context)

        llm = context.llm
        assert isinstance(llm, ConcurrencyWatchingLLM)
        assert llm.peak_in_flight == 1

    async def test_the_default_ceiling_is_documented_and_above_one(self) -> None:
        assert DEFAULT_MAX_CONCURRENT_BATCHES > 1

    async def test_results_keep_corpus_order_not_completion_order(self) -> None:
        """§4.5's split and §4.1's ordering must not depend on which call won."""
        context = self._watching(ALL, batch_size=1)

        await CommentAnalysisStep(batch_size=1, max_concurrent_batches=4).run(context)

        analysed = [analysis.comment_id for analysis in context.data["comment_analyses"]]
        assert analysed == [entry.id for entry in ALL]

    async def test_two_concurrent_runs_over_one_corpus_agree(self) -> None:
        """Determinism is the acceptance criterion concurrency most threatens."""
        first = self._watching(ALL, batch_size=2)
        second = self._watching(ALL, batch_size=2)

        await CommentAnalysisStep(batch_size=2, max_concurrent_batches=4).run(first)
        await CommentAnalysisStep(batch_size=2, max_concurrent_batches=4).run(second)

        assert first.research.statistics == second.research.statistics
        assert first.research.diagnostics.suppressions == second.research.diagnostics.suppressions
        assert [a.comment_id for a in first.data["comment_analyses"]] == [
            a.comment_id for a in second.data["comment_analyses"]
        ]


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
        counted = CLEAR
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
        counted = CLEAR
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


class TestTheDeadlineStopsAdmissionNeverCompletion:
    """Plan §2.12.2. maxResearchDuration went unread until here: the measured
    run finished in 2408 s against a 300 s budget and nothing noticed."""

    def _timed(
        self, entries: Sequence[LabeledComment], *, started: datetime, clock: Clock
    ) -> PipelineContext:
        context = make_context(
            llm=SlowLLM([expected_batch((entry,)) for entry in entries], clock=clock),
            status=ResearchStatus.ANALYZING,
        )
        context.data["counted_comments"] = [entry.as_comment() for entry in entries]
        context.data["evidence_comments"] = []
        mark_started(context, now=started)
        return context

    async def test_no_batch_is_dispatched_after_the_deadline(self) -> None:
        clock = Clock(START, per_call=timedelta(seconds=60))
        context = self._timed(ALL, started=START, clock=clock)

        await CommentAnalysisStep(
            batch_size=1, max_concurrent_batches=1, clock=clock.read
        ).run(context)

        # 300 s budget, 60 s reserve: the window is 240 s, and each call
        # costs 60 s. One wave is exempt, then four more fit.
        assert clock.calls == 5
        assert context.research.statistics["comments_not_analysed_budget"] == len(ALL) - 5

    async def test_a_batch_in_flight_when_the_deadline_passes_is_still_kept(self) -> None:
        """Its tokens are already paid for; dropping the answer buys nothing."""
        clock = Clock(START, per_call=timedelta(seconds=1000))
        context = self._timed(ALL, started=START, clock=clock)

        await CommentAnalysisStep(
            batch_size=1, max_concurrent_batches=1, clock=clock.read
        ).run(context)

        analysed = [analysis.comment_id for analysis in context.data["comment_analyses"]]
        assert analysed == [ALL[0].id]
        assert context.research.statistics["comments_with_analysis"] == 1

    async def test_one_wave_goes_out_even_when_the_deadline_has_already_passed(self) -> None:
        """Full cost and no evidence is the worst outcome available (§2.12.2)."""
        clock = Clock(START + timedelta(hours=1), per_call=timedelta(0))
        context = self._timed(ALL, started=START, clock=clock)

        await CommentAnalysisStep(
            batch_size=1, max_concurrent_batches=3, clock=clock.read
        ).run(context)

        assert len(context.data["comment_analyses"]) == 3
        assert context.research.statistics["comments_not_analysed_budget"] == len(ALL) - 3

    async def test_the_dispatch_deadline_is_the_budget_minus_the_tail_reserve(self) -> None:
        """Derived from the promise, not equal to it — five minutes must not mean seven."""
        context = make_context(status=ResearchStatus.ANALYZING)
        budget = context.research.research_config.budget
        mark_started(context, now=START)

        assert admission_deadline(context) == START + timedelta(
            seconds=budget.max_research_duration_seconds - budget.tail_reserve_seconds
        )
        assert budget.tail_reserve_seconds == 60

    async def test_undispatched_comments_are_budget_limited_not_failed(self) -> None:
        """Two different claims: "we stopped on purpose" against "we could not see"."""
        clock = Clock(START + timedelta(hours=1), per_call=timedelta(0))
        context = self._timed(ALL, started=START, clock=clock)

        await CommentAnalysisStep(
            batch_size=1, max_concurrent_batches=1, clock=clock.read
        ).run(context)

        statistics = context.research.statistics
        assert statistics["comments_not_analysed_budget"] == len(ALL) - 1
        assert statistics["comments_lost_to_errors"] == 0
        assert _suppressions(context, SuppressionReason.BUDGET_MAX_RESEARCH_DURATION) == [
            len(ALL) - 1
        ]
        assert _suppressions(context, SuppressionReason.ANALYSIS_BATCH_FAILED) == []

    async def test_expiry_names_its_limiting_factor(self) -> None:
        clock = Clock(START + timedelta(hours=1), per_call=timedelta(0))
        context = self._timed(ALL, started=START, clock=clock)

        await CommentAnalysisStep(
            batch_size=1, max_concurrent_batches=1, clock=clock.read
        ).run(context)

        (entry,) = [
            suppression
            for suppression in context.research.diagnostics.suppressions
            if suppression.reason is SuppressionReason.BUDGET_MAX_RESEARCH_DURATION
        ]
        assert entry.detail is not None
        assert "300s budget" in entry.detail
        assert "60s tail reserve" in entry.detail
        assert ResearchFlag.BUDGET_LIMIT_REACHED in context.research.diagnostics.flags

    async def test_a_run_inside_its_budget_dispatches_everything(self) -> None:
        clock = Clock(START, per_call=timedelta(seconds=1))
        context = self._timed(ALL, started=START, clock=clock)

        await CommentAnalysisStep(
            batch_size=1, max_concurrent_batches=2, clock=clock.read
        ).run(context)

        assert len(context.data["comment_analyses"]) == len(ALL)
        assert context.research.statistics["comments_not_analysed_budget"] == 0
        assert context.research.diagnostics.flags == []


class TestOneFailedBatchDoesNotTakeTheRunWithIt:
    """Plan §2.12/14.6c. The run before the measured one died at 1487 s on a
    single OpenAI connection error, throwing away 24 minutes of finished work."""

    def _failing(
        self, entries: Sequence[LabeledComment], *, fails: Sequence[int], error: Exception
    ) -> PipelineContext:
        batches = [(entry,) for entry in entries]
        answers: list[CommentAnalysisBatch | Exception] = [
            error if index in fails else expected_batch(batch)
            for index, batch in enumerate(batches)
        ]
        context = make_context(llm=FlakyLLM(answers), status=ResearchStatus.ANALYZING)
        context.data["counted_comments"] = [entry.as_comment() for entry in entries]
        context.data["evidence_comments"] = []
        return context

    async def test_the_other_batches_results_are_kept(self) -> None:
        context = self._failing(ALL, fails=[1], error=LLMUnavailableError("connection reset"))

        await CommentAnalysisStep(batch_size=1, max_concurrent_batches=2).run(context)

        analysed = {analysis.comment_id for analysis in context.data["comment_analyses"]}
        assert analysed == {entry.id for entry in ALL} - {ALL[1].id}

    async def test_the_loss_is_counted_and_named(self) -> None:
        context = self._failing(ALL, fails=[0, 2], error=LLMUnavailableError("rate limited"))

        await CommentAnalysisStep(batch_size=1, max_concurrent_batches=2).run(context)

        statistics = context.research.statistics
        assert statistics["analysis_batches_attempted"] == len(ALL)
        assert statistics["analysis_batches_failed"] == 2
        assert statistics["comments_lost_to_errors"] == 2
        assert _suppressions(context, SuppressionReason.ANALYSIS_BATCH_FAILED) == [2]

    async def test_the_failure_kind_reaches_the_health_table(self) -> None:
        """§8.1: batches attempted, batches failed, failure kinds — like a source."""
        context = self._failing(ALL, fails=[0], error=LLMUnavailableError("502"))

        await CommentAnalysisStep(batch_size=1, max_concurrent_batches=2).run(context)

        recorder = get_recorder(context)
        (entry,) = [e for e in recorder.snapshot() if e.adapter == ANALYSIS_ADAPTER]
        assert entry.calls_attempted == len(ALL)
        assert entry.calls_failed == 1
        assert entry.failure_kinds == {FailureKind.LLM_UNAVAILABLE: 1}

    async def test_a_missing_credential_is_still_fatal(self) -> None:
        """Not a property of one batch: no credential means nothing can be analysed,
        and a configuration error must not arrive as a quiet degradation (§0.1)."""
        context = self._failing(ALL, fails=[2], error=LLMCredentialError("no API key"))

        with pytest.raises(LLMCredentialError):
            await CommentAnalysisStep(batch_size=1, max_concurrent_batches=2).run(context)

    async def test_a_run_that_lost_batches_is_distinguishable_from_a_thin_one(self) -> None:
        """The §0.1 pair, for LLM failure: a lost quarter must not read as a quiet corpus."""
        floors = SourceHealthFloors(min_comments_analyzed=len(ALL), min_posts_retrieved=0)

        lost = self._failing(ALL, fails=[0, 1], error=LLMUnavailableError("gateway"))
        lost.research.research_config.source_health_floors = floors
        lost.data["source_assessment"] = _healthy_assessment()

        thin = _context(counted=ALL, responses=[expected_batch(ALL)])
        thin.research.research_config.source_health_floors = floors
        thin.data["source_assessment"] = _healthy_assessment()

        await CommentAnalysisStep(batch_size=1, max_concurrent_batches=2).run(lost)
        await CommentAnalysisStep().run(thin)

        assert lost.research.diagnostics.source_outcome is SourceOutcome.DEGRADED
        assert thin.research.diagnostics.source_outcome is SourceOutcome.HEALTHY
        assert lost.research.statistics["comments_lost_to_errors"] == 2
        assert thin.research.statistics["comments_lost_to_errors"] == 0

    async def test_losing_nothing_leaves_the_earlier_verdict_alone(self) -> None:
        context = _context(counted=ALL, responses=[expected_batch(ALL)])
        context.research.research_config.source_health_floors = SourceHealthFloors(
            min_comments_analyzed=0, min_posts_retrieved=0
        )
        context.data["source_assessment"] = _healthy_assessment()

        await CommentAnalysisStep().run(context)

        assert context.research.diagnostics.source_outcome is SourceOutcome.HEALTHY


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
        empty = CommentAnalysisBatch(items=[_analysis(entry.id) for entry in CLEAR])
        context = _context(counted=CLEAR, responses=[empty])
        await CommentAnalysisStep().run(context)
        return context

    @staticmethod
    async def _suppressed_run() -> PipelineContext:
        """The model recommended plenty, and every quote was invented."""
        fabricated = CommentAnalysisBatch(
            items=[
                _analysis(entry.id, _mention(supporting_quote="never written by anyone"))
                for entry in CLEAR
            ]
        )
        context = _context(counted=CLEAR, responses=[fabricated])
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
        assert _suppressions(suppressed, SuppressionReason.ANALYSIS_FABRICATED_QUOTE) == [
            len(CLEAR)
        ]

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
        assert suppressed.research.statistics["analysis_mentions_fabricated_quote"] == len(CLEAR)


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
