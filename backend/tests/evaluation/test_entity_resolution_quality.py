"""Does the *model* resolve names well enough? (plan §9, §10 Phase 9.)

Every other Phase 9 test asks whether our code handles an answer correctly,
and answers it offline. This one asks the other question — whether a real
model, given the step 8 prompt, actually turns a nickname the catalogue
does not hold into the right state, and whether it declines to name a place
when there is none — and the only way to answer that is to ask a model.

So it lives in the evaluation tier: marked, excluded from ``make test`` and
from CI by ``addopts`` in ``pyproject.toml``, and run deliberately::

    set -a; . .env; set +a; uv run pytest -m evaluation

One call resolves the whole set, and every assertion reads from that one
result, so a full run costs a single request.
"""

from __future__ import annotations

import pytest

from builders.phase7 import make_context, make_plan
from tripfinder.ai.factory import LLMProviderName, build_llm_provider
from tripfinder.analysis.comment_analysis import CommentAnalysis, EntityMention
from tripfinder.domain.models import (
    EntityResolutionMethod,
    EntityResolutionOutcome,
    EntityType,
    ResearchStatus,
    Stance,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.entity_resolution import EntityResolutionStep
from tripfinder.settings import Settings

pytestmark = pytest.mark.evaluation

FORMS: tuple[tuple[str, str], ...] = (
    ("the Mitten", "the Mitten has more freshwater coastline than anywhere else"),
    ("Massachussetts", "western Massachussetts in October is unbeatable"),
    ("the state Denali is in", "the state Denali is in has no crowds at all"),
    ("my ex's cabin", "my ex's cabin was the best part of that trip"),
    ("Michigan", "Michigan is hands down the most underrated state for nature"),
)

_RUN: PipelineContext | None = None


def _mention(raw_text: str, quote: str) -> EntityMention:
    return EntityMention(
        raw_text=raw_text,
        normalized_guess=raw_text,
        entity_type=EntityType.STATE,
        stance=Stance.POSITIVE,
        strength=0.8,
        supporting_quote=quote,
    )


async def _run() -> PipelineContext:
    """The real model's reading of the whole set — one call per session."""
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
    context.data["plan"] = make_plan(EntityType.STATE)
    context.data["counted_analyses"] = [
        CommentAnalysis(
            comment_id=f"c{index}",
            topic_relevance=0.9,
            criterion_relevance=0.9,
            scope_match=True,
            overall_confidence=0.9,
            mentions=[_mention(raw_text, quote)],
            reasoning="evaluation fixture",
        )
        for index, (raw_text, quote) in enumerate(FORMS)
    ]
    context.data["evidence_analyses"] = []

    await EntityResolutionStep(batch_size=len(FORMS)).run(context)

    _RUN = context
    return context


async def _outcome(surface_form: str) -> EntityResolutionOutcome:
    context = await _run()
    for entry in context.research.diagnostics.entity_resolutions:
        if entry.surface_form == surface_form:
            return entry
    raise LookupError(surface_form)


async def test_a_known_name_never_reaches_the_model() -> None:
    """It is the catalogue's answer, and it costs nothing."""
    assert (await _outcome("Michigan")).decided_by is EntityResolutionMethod.RULE


async def test_a_nickname_the_catalog_does_not_hold_resolves_to_its_state() -> None:
    outcome = await _outcome("the Mitten")

    assert outcome.decided_by is EntityResolutionMethod.AI
    assert outcome.canonical_name == "Michigan"


async def test_a_misspelling_resolves_to_the_state_meant() -> None:
    assert (await _outcome("Massachussetts")).canonical_name == "Massachusetts"


async def test_a_description_of_a_state_resolves_to_that_state() -> None:
    """Semantic, not lexical: the surface form shares no word with the answer."""
    assert (await _outcome("the state Denali is in")).canonical_name == "Alaska"


async def test_something_that_is_not_a_place_is_left_unresolved() -> None:
    """`PROJECT.md` §15's erring direction, asked of the model itself."""
    outcome = await _outcome("my ex's cabin")

    assert outcome.entity_id is None
    assert outcome.reason


async def test_the_nickname_and_the_name_end_up_as_one_entity() -> None:
    context = await _run()

    assert [entity.canonical_name for entity in context.data["entities"]] == [
        "Alaska",
        "Massachusetts",
        "Michigan",
    ]
