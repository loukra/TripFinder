"""Does the *model* read comments well enough? (plan §9, §10 Phase 8 acceptance.)

Every other Phase 8 test asks whether our code handles an answer correctly,
and answers it offline. This one asks the other question — whether a real
model, given the §5 prompt, actually recognises a recommendation written in
words the query never used — and the only way to answer that is to ask a
model.

So it lives in the evaluation tier: marked, excluded from ``make test`` and
from CI by ``addopts`` in ``pyproject.toml``, and run deliberately::

    set -a; . .env; set +a; uv run pytest -m evaluation

One call analyses the whole labeled corpus, and every assertion reads from
that one result, so a full run costs a single request.
"""

from __future__ import annotations

import pytest

from builders.labeled_comments import LabeledComment, labeled_comments
from builders.phase7 import make_context
from tripfinder.ai.factory import LLMProviderName, build_llm_provider
from tripfinder.analysis.comment_analysis import CommentAnalysis
from tripfinder.domain.models import ResearchStatus, Stance
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.comment_analysis import CommentAnalysisStep
from tripfinder.settings import Settings

pytestmark = pytest.mark.evaluation

ALL = labeled_comments()

_RUN: PipelineContext | None = None


async def _run() -> PipelineContext:
    """The real model's reading of the whole corpus — one call per session."""
    global _RUN
    if _RUN is not None:
        return _RUN

    settings = Settings.from_env()
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not set — see the module docstring")

    provider = build_llm_provider(
        LLMProviderName.OPENAI, openai_api_key=settings.openai_api_key
    )
    context = make_context(llm=provider, status=ResearchStatus.ANALYZING)
    context.data["counted_comments"] = [entry.as_comment() for entry in ALL]
    context.data["evidence_comments"] = []

    await CommentAnalysisStep(batch_size=len(ALL)).run(context)

    _RUN = context
    return context


async def _analysed() -> dict[str, CommentAnalysis]:
    context = await _run()
    return {analysis.comment_id: analysis for analysis in context.data["comment_analyses"]}


def _positive(analysis: CommentAnalysis) -> bool:
    return any(mention.stance is Stance.POSITIVE for mention in analysis.mentions)


def _names(analysis: CommentAnalysis) -> str:
    return " | ".join(
        f"{mention.raw_text}->{mention.normalized_guess}" for mention in analysis.mentions
    )


@pytest.mark.parametrize("entry", ALL, ids=lambda entry: str(entry.id))
async def test_every_comment_is_analysed(entry: LabeledComment) -> None:
    assert entry.id in await _analysed()


@pytest.mark.parametrize("entry", ALL, ids=lambda entry: str(entry.id))
async def test_relevance_matches_the_label(entry: LabeledComment) -> None:
    analysis = (await _analysed())[entry.id]

    assert (analysis.topic_relevance >= 0.5) is entry.expect_relevant, analysis.reasoning


RECOMMENDING = [entry for entry in ALL if entry.mention is not None]


@pytest.mark.parametrize("entry", RECOMMENDING, ids=lambda entry: str(entry.id))
async def test_the_expected_places_are_recognised(entry: LabeledComment) -> None:
    """Including the ones named only by nickname — the acceptance criterion."""
    assert entry.mention is not None
    analysis = (await _analysed())[entry.id]
    guesses = " ".join(mention.normalized_guess.lower() for mention in analysis.mentions)

    assert entry.mention.entity.lower() in guesses, _names(analysis)


@pytest.mark.parametrize("entry", ALL, ids=lambda entry: str(entry.id))
async def test_stance_matches_the_label(entry: LabeledComment) -> None:
    """An ambiguous or irrelevant comment must not read as a vote."""
    analysis = (await _analysed())[entry.id]

    assert _positive(analysis) is entry.expect_positive, _names(analysis)


async def test_the_model_quotes_verbatim() -> None:
    """Every mention it made survived verification — nothing had to be discarded."""
    context = await _run()

    assert context.research.statistics["analysis_mentions_fabricated_quote"] == 0


async def test_every_relevant_comment_yields_at_least_one_mention() -> None:
    analysed = await _analysed()
    relevant = [entry for entry in ALL if entry.expect_relevant]

    empty = [entry.id for entry in relevant if not analysed[entry.id].mentions]
    assert empty == []
