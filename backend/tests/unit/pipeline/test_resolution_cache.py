"""A provisional ranking for a question the catalogue knows nothing about.

Plan §2.13 forbids a snapshot from calling the model, so entity resolution
runs deterministically inside one — normalisation plus the alias table. The
alias table holds one tier, the fifty US states. Nobody wrote a test with
any other tier, and so for eighteen months the provisional ranking was
empty for every question that was not about US states: measured on a real
run about national parks, 1120 surface forms and
``entity_forms_resolved_by_rule: 0``, the first ranking appearing six and a
half minutes in because it was the *final* one.

This file is the test that was missing, and the mechanism that answers it:
the run puts names to the model while it is still reading, into a cache the
snapshot reads without calling anything.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel

from builders.phase7 import make_comment, make_context, make_plan
from tripfinder.analysis.comment_analysis import CommentAnalysis, EntityMention
from tripfinder.analysis.entity_resolution import EntityResolutionBatch, ResolvedName
from tripfinder.domain.config import RankingConfig, ResearchConfig
from tripfinder.domain.models import EntityType, ReasonCode, ResearchStatus, Result, Stance
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.snapshot import snapshot
from tripfinder.pipeline.steps.entity_resolution import EntityResolutionStep
from tripfinder.pipeline.streaming.resolution import ResolutionCache

_LISTING = re.compile(r"^Names \(\d+\):$(.*)", re.MULTILINE | re.DOTALL)
_ASKED = re.compile(r"^- surface_form: (.+)$", re.MULTILINE)


def _forms_in(prompt: str) -> list[str]:
    """The names one call actually asked about — the listing, not the instructions."""
    listing = _LISTING.search(prompt)
    assert listing is not None, "the prompt no longer carries a listing of names"
    return _ASKED.findall(listing.group(1))

# Names of national parks, written as people write them. Not one of them is
# in the alias table, which holds US states and nothing else.
CORPUS: tuple[tuple[str, str, str], ...] = (
    ("c1", "u1", "Canyonlands"),
    ("c2", "u2", "Canyonlands NP"),
    ("c3", "u3", "North Cascades"),
    ("c4", "u4", "North Cascades National Park"),
    ("c5", "u5", "Great Basin"),
)

CANONICAL = {
    "Canyonlands": "Canyonlands National Park",
    "Canyonlands NP": "Canyonlands National Park",
    "North Cascades": "North Cascades National Park",
    "North Cascades National Park": "North Cascades National Park",
    "Great Basin": "Great Basin National Park",
}


class ResolvingLLM:
    """Answers a resolution batch the way the real model does: one item per name.

    It reads the forms out of the prompt rather than being handed them, so a
    call that asks about the wrong names, or asks twice about the same one,
    shows up here as a wrong answer rather than passing silently.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.batches: list[list[str]] = []

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        self.calls += 1
        asked = _forms_in(prompt)
        self.batches.append(asked)
        assert response_model is EntityResolutionBatch
        answer = EntityResolutionBatch(
            items=[
                ResolvedName(
                    surface_form=form,
                    canonical_name=CANONICAL.get(form),
                    confidence=0.95,
                    reason="a national park by that name",
                )
                for form in asked
            ]
        )
        assert isinstance(answer, response_model)
        return answer


def _mention(raw_text: str) -> EntityMention:
    return EntityMention(
        raw_text=raw_text,
        entity_type=EntityType.PARK,
        stance=Stance.POSITIVE,
        strength=0.8,
        supporting_quote="a verbatim span",
    )


def _analyses(corpus: Sequence[tuple[str, str, str]] = CORPUS) -> list[CommentAnalysis]:
    return [
        CommentAnalysis(
            comment_id=comment_id,
            topic_relevance=0.9,
            criterion_relevance=0.9,
            scope_match=True,
            overall_confidence=0.9,
            mentions=[_mention(name)],
            reason_code=ReasonCode.RECOMMENDS,
        )
        for comment_id, _, name in corpus
    ]


def _context(*, llm: ResolvingLLM | None = None, cached: bool = True) -> PipelineContext:
    """A run mid-analysis, asking about parks rather than states."""
    context = make_context(
        llm=llm or ResolvingLLM(),
        config=ResearchConfig(ranking=RankingConfig(minimum_independent_users=2)),
        status=ResearchStatus.ANALYZING,
    )
    context.data["plan"] = make_plan(EntityType.PARK)
    context.data["comments"] = [
        make_comment(comment_id, user_id=user_id) for comment_id, user_id, _ in CORPUS
    ]
    if cached:
        context.data["resolution_cache"] = ResolutionCache()
    return context


async def _prime(context: PipelineContext, *, batch_size: int = 50) -> int:
    return await EntityResolutionStep(batch_size=batch_size).prime(
        context, counted_analyses=_analyses(), evidence_analyses=[]
    )


def _named(results: tuple[list[Result], list[Result]]) -> list[tuple[str, int]]:
    strong, weak = results
    return [(result.entity_name, result.supporter_count) for result in [*strong, *weak]]


class TestASnapshotRanksWhatTheCatalogueCannotPlace:
    async def test_with_nothing_primed_a_park_question_ranks_nothing(self) -> None:
        """The defect, pinned. Not one of these names is in the alias table,
        so the deterministic half places none of them — which is honest, and
        was until now the whole of what a snapshot could show for any
        question that is not about US states."""
        llm = ResolvingLLM()

        ranked = await snapshot(
            _context(llm=llm), counted_analyses=_analyses(), evidence_analyses=[]
        )

        assert _named(ranked) == []
        assert llm.calls == 0

    async def test_once_the_names_are_primed_the_same_snapshot_ranks_them(self) -> None:
        llm = ResolvingLLM()
        context = _context(llm=llm)

        await _prime(context)
        calls_after_priming = llm.calls
        ranked = await snapshot(
            context, counted_analyses=_analyses(), evidence_analyses=[]
        )

        assert _named(ranked) == [
            ("Canyonlands National Park", 2),
            ("North Cascades National Park", 2),
            ("Great Basin National Park", 1),
        ]
        # Two spellings of one park are that park twice, not two parks once.
        assert calls_after_priming == 1
        # And the snapshot itself still calls nothing at all (plan §2.13).
        assert llm.calls == calls_after_priming

    async def test_a_run_without_a_cache_behaves_exactly_as_it_did_before(self) -> None:
        """Every caller that does not set one up — every test of steps 8-11,
        every non-streaming pipeline — must be untouched by this."""
        llm = ResolvingLLM()
        context = _context(llm=llm, cached=False)

        asked = await _prime(context)
        ranked = await snapshot(
            context, counted_analyses=_analyses(), evidence_analyses=[]
        )

        assert asked == 0
        assert llm.calls == 0
        assert _named(ranked) == []


class TestPrimingDecidesNothing:
    """Plan §2.13.2: a run that is still reading has settled nothing. Priming
    is a call made early, not an answer published early."""

    async def test_it_writes_no_resolutions_entities_or_status(self) -> None:
        context = _context()
        before = context.research.status

        await _prime(context)

        assert context.research.diagnostics.entity_resolutions == []
        assert context.research.diagnostics.suppressions == []
        assert context.research.results == []
        assert "entities" not in context.data
        assert "resolved_mentions" not in context.data
        assert context.research.status is before

    async def test_the_final_pass_records_everything_as_it_always_did(self) -> None:
        """The diagnostics belong to the run's own pass over a closed corpus —
        so priming must not rob it of them (plan §0.1)."""
        context = _context()
        await _prime(context)

        context.data["counted_analyses"] = _analyses()
        context.data["evidence_analyses"] = []
        await EntityResolutionStep().run(context)

        outcomes = context.research.diagnostics.entity_resolutions
        assert {outcome.surface_form for outcome in outcomes} == {name for _, _, name in CORPUS}
        assert context.research.statistics["entity_forms_resolved_by_ai"] == 5


class TestItCostsTheCallsItAlwaysDid:
    async def test_only_whole_batches_are_asked_for(self) -> None:
        """A cache that asked after every analysis batch would turn thirteen
        calls into seventy. The remainder waits for the next batch of names."""
        llm = ResolvingLLM()
        context = _context(llm=llm)

        asked = await _prime(context, batch_size=3)

        assert asked == 3
        assert llm.batches == [["Canyonlands", "Canyonlands NP", "North Cascades"]]
        assert llm.calls == 1

    async def test_the_first_names_are_asked_about_however_few_they_are(self) -> None:
        """Otherwise a question whose whole corpus names a dozen places would
        never preview at all — which is the defect this file exists for, just
        rarer."""
        llm = ResolvingLLM()
        context = _context(llm=llm)

        asked = await _prime(context, batch_size=50)

        assert asked == len(CORPUS)
        assert llm.calls == 1

    async def test_after_the_first_call_a_partial_batch_waits(self) -> None:
        llm = ResolvingLLM()
        context = _context(llm=llm)
        await _prime(context, batch_size=2)  # asks about four of the five

        asked = await _prime(context, batch_size=2)

        assert asked == 0
        assert llm.calls == 2

    async def test_the_final_pass_asks_only_for_what_the_cache_lacks(self) -> None:
        llm = ResolvingLLM()
        context = _context(llm=llm)
        await _prime(context, batch_size=3)

        context.data["counted_analyses"] = _analyses()
        context.data["evidence_analyses"] = []
        await EntityResolutionStep(batch_size=3).run(context)

        # One call primed three names; the final pass asks about the two left.
        assert llm.batches == [
            ["Canyonlands", "Canyonlands NP", "North Cascades"],
            ["North Cascades National Park", "Great Basin"],
        ]

    async def test_a_name_is_never_put_to_the_model_twice(self) -> None:
        llm = ResolvingLLM()
        context = _context(llm=llm)

        await _prime(context, batch_size=1)
        await _prime(context, batch_size=1)

        assert sum(len(batch) for batch in llm.batches) == len(CORPUS)
        assert sorted(form for batch in llm.batches for form in batch) == sorted(
            name for _, _, name in CORPUS
        )
