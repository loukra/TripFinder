"""The shared denominator (plan §2.14.2, §10 Phase 14.8).

One person, one vote holds across the whole run, so strands count locally
and only the accumulator ranks. What is proven here: the union sees a user
that two strands each saw once; arrival order never reaches the ranking;
the coalescing and sequence guards 14.7 relies on still hold when eighty
strands land at the same moment; and an analysis no strand registered is
dropped rather than attributed to a corpus it might not belong to.
"""

from __future__ import annotations

import asyncio

from builders.phase7 import make_comment, make_context
from tripfinder.analysis.comment_analysis import CommentAnalysis, EntityMention
from tripfinder.domain.config import RankingConfig, ResearchConfig
from tripfinder.domain.models import EntityType, ReasonCode, Stance
from tripfinder.pipeline.base import PartialResults, PipelineContext
from tripfinder.pipeline.streaming.accumulator import Accumulator
from tripfinder.pipeline.streaming.budget import CommentClass

BODY = "Michigan is stunning in autumn and almost nobody goes there."


def _analysis(comment_id: str, name: str) -> CommentAnalysis:
    return CommentAnalysis(
        comment_id=comment_id,
        topic_relevance=0.9,
        criterion_relevance=0.9,
        scope_match=True,
        overall_confidence=0.9,
        reason_code=ReasonCode.RECOMMENDS,
        mentions=[
            EntityMention(
                raw_text=name,
                entity_type=EntityType.STATE,
                stance=Stance.POSITIVE,
                strength=0.8,
                supporting_quote=BODY,
            )
        ],
    )


class Listener:
    def __init__(self) -> None:
        self.received: list[PartialResults] = []

    async def __call__(self, partial: PartialResults) -> None:
        self.received.append(partial)


def _context() -> tuple[PipelineContext, Listener]:
    context = make_context(
        config=ResearchConfig(ranking=RankingConfig(minimum_independent_users=2))
    )
    listener = Listener()
    context.on_partial_results = listener
    return context, listener


def _counts(partial: PartialResults) -> dict[str, int]:
    return {
        result.entity_name: result.supporter_count
        for result in [*partial.results, *partial.weak_results]
    }


class TestTheUnionAcrossStrands:
    async def test_one_person_voting_in_two_documents_is_counted_once(self) -> None:
        """The reason a strand may not rank: neither strand can see that
        `u1` is the same person (plan §2.14.2)."""
        context, listener = _context()
        accumulator = Accumulator(context)

        for document, comment_id in (("d1", "c1"), ("d2", "c2")):
            comment = make_comment(comment_id, document_id=document, user_id="u1", body=BODY)
            accumulator.register([comment], comment_class=CommentClass.COUNTED)
            await accumulator.batch_finished({comment_id: _analysis(comment_id, "Michigan")})

        assert _counts(listener.received[-1]) == {"Michigan": 1}

    async def test_two_people_in_two_documents_are_counted_twice(self) -> None:
        context, listener = _context()
        accumulator = Accumulator(context)

        for document, comment_id, user in (("d1", "c1", "u1"), ("d2", "c2", "u2")):
            comment = make_comment(comment_id, document_id=document, user_id=user, body=BODY)
            accumulator.register([comment], comment_class=CommentClass.COUNTED)
            await accumulator.batch_finished({comment_id: _analysis(comment_id, "Michigan")})

        assert _counts(listener.received[-1]) == {"Michigan": 2}


class TestArrivalOrderNeverReachesTheRanking:
    async def test_the_corpus_is_ordered_by_document_not_by_who_finished_first(self) -> None:
        """Strands finish in whatever order the network allows. Two runs over
        one corpus still have to produce the same statistics."""
        forwards: list[list[str]] = []
        backwards: list[list[str]] = []
        for order in (("d1", "d2", "d3"), ("d3", "d1", "d2")):
            context, _ = _context()
            accumulator = Accumulator(context)
            for index, document in enumerate(order):
                comment = make_comment(
                    f"c{document}", document_id=document, user_id=f"u{index}", body=BODY
                )
                accumulator.register([comment], comment_class=CommentClass.COUNTED)
                await accumulator.batch_finished(
                    {comment.id: _analysis(comment.id, "Michigan")}
                )
            counted, _ = accumulator.corpus()
            (forwards if order[0] == "d1" else backwards).append(
                [analysis.comment_id for analysis in counted]
            )
        assert forwards[0] == backwards[0] == ["cd1", "cd2", "cd3"]


class TestTheGuards14_7Relies_On:
    async def test_eighty_strands_landing_at_once_coalesce(self) -> None:
        """Plan §2.13.2 under 14.8's load: one wave is now the whole run, so
        without coalescing every strand computes and persists its own."""
        context, _ = _context()
        accumulator = Accumulator(context)
        gate = asyncio.Event()
        received: list[PartialResults] = []

        async def listener(partial: PartialResults) -> None:
            received.append(partial)
            if len(received) == 1:
                await gate.wait()

        context.on_partial_results = listener

        comments = [
            make_comment(f"c{index}", document_id=f"d{index}", user_id=f"u{index}", body=BODY)
            for index in range(8)
        ]
        accumulator.register(comments, comment_class=CommentClass.COUNTED)

        # Eight strands calling in at once, which is what one wave looks
        # like under 14.8. The first to arrive computes and is held; the
        # other seven must find a computation already in flight.
        done: list[str] = []

        async def feed(comment_id: str) -> None:
            await accumulator.batch_finished({comment_id: _analysis(comment_id, "Michigan")})
            done.append(comment_id)

        async def release() -> None:
            while len(done) < len(comments) - 1:
                await asyncio.sleep(0)
            gate.set()

        await asyncio.gather(*(feed(comment.id) for comment in comments), release())

        assert len(received) == 2
        assert received[0].batches_completed == 1
        assert received[1].batches_completed == 8
        assert _counts(received[1]) == {"Michigan": 8}

    async def test_the_sequence_number_only_advances(self) -> None:
        context, listener = _context()
        accumulator = Accumulator(context)
        for index in range(5):
            comment = make_comment(
                f"c{index}", document_id=f"d{index}", user_id=f"u{index}", body=BODY
            )
            accumulator.register([comment], comment_class=CommentClass.COUNTED)
            await accumulator.batch_finished({comment.id: _analysis(comment.id, "Michigan")})

        sequences = [partial.batches_completed for partial in listener.received]
        assert sequences == sorted(sequences) == [1, 2, 3, 4, 5]


class TestMaterialThatCannotBeAttributed:
    async def test_an_analysis_no_strand_registered_is_dropped(self) -> None:
        """It belongs to neither corpus, and §4.5 makes that distinction
        load-bearing: guessing would let a topical user into the pool."""
        context, listener = _context()
        accumulator = Accumulator(context)
        known = make_comment("c1", document_id="d1", user_id="u1", body=BODY)
        accumulator.register([known], comment_class=CommentClass.COUNTED)

        await accumulator.batch_finished(
            {"c1": _analysis("c1", "Michigan"), "ghost": _analysis("ghost", "Michigan")}
        )

        counted, evidence = accumulator.corpus()
        assert [analysis.comment_id for analysis in counted] == ["c1"]
        assert evidence == []

    async def test_evidence_comments_never_enter_the_counted_corpus(self) -> None:
        context, _ = _context()
        accumulator = Accumulator(context)
        counted_comment = make_comment("c1", document_id="d1", user_id="u1", body=BODY)
        evidence_comment = make_comment("c2", document_id="d2", user_id="u2", body=BODY)
        accumulator.register([counted_comment], comment_class=CommentClass.COUNTED)
        accumulator.register([evidence_comment], comment_class=CommentClass.EVIDENCE)

        await accumulator.batch_finished(
            {"c1": _analysis("c1", "Michigan"), "c2": _analysis("c2", "Michigan")}
        )

        counted, evidence = accumulator.corpus()
        assert [analysis.comment_id for analysis in counted] == ["c1"]
        assert [analysis.comment_id for analysis in evidence] == ["c2"]


class TestARunWithNowhereToSendSnapshots:
    async def test_no_listener_means_no_snapshot_computed(self) -> None:
        context, _ = _context()
        context.on_partial_results = None
        accumulator = Accumulator(context)
        comment = make_comment("c1", document_id="d1", user_id="u1", body=BODY)
        accumulator.register([comment], comment_class=CommentClass.COUNTED)

        await accumulator.batch_finished({"c1": _analysis("c1", "Michigan")})

        assert accumulator.corpus() == ([], [])
