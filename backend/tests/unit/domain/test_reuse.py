"""The reuse key (plan §2.15): when are two questions the same question?

The whole feature rests on this function. Too loose and a run answers a
question nobody asked; too tight and the cache never hits and the phase
delivers nothing.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from tripfinder.domain.models import EntityType, GeoScope, ResearchPlan
from tripfinder.domain.reuse import plan_fingerprint


def _plan(**overrides: object) -> ResearchPlan:
    fields: dict[str, object] = {
        "normalized_query": "best national parks for avoiding crowds",
        "scope": GeoScope(type="country", value="United States"),
        "entity_granularity": EntityType.PARK,
        "granularity_confidence": 0.9,
        "topic": "national parks",
        "criteria": ["uncrowded", "scenic"],
        "seed_queries": ["quiet national parks reddit"],
        "candidate_subreddits": ["NationalPark"],
    }
    fields.update(overrides)
    return ResearchPlan.model_validate(fields)


def test_the_same_plan_gives_the_same_key() -> None:
    assert plan_fingerprint(_plan()) == plan_fingerprint(_plan())


def test_the_key_survives_a_process_restart() -> None:
    """It is a digest, not ``hash()`` — a key stored today must match tomorrow.

    Python salts ``hash()`` of a string per process, so a fingerprint built
    on it would stop matching the moment the worker restarted: reuse would
    pass every test in this file and never once hit in production. Two
    interpreters with deliberately different hash seeds settle it.
    """
    program = (
        "from tripfinder.domain.models import EntityType, GeoScope, ResearchPlan;"
        "from tripfinder.domain.reuse import plan_fingerprint;"
        "print(plan_fingerprint(ResearchPlan("
        "normalized_query='best national parks for avoiding crowds',"
        "scope=GeoScope(type='country', value='United States'),"
        "entity_granularity=EntityType.PARK, granularity_confidence=0.9,"
        "topic='national parks', criteria=['uncrowded', 'scenic'])))"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env={
                **os.environ,
                "PYTHONHASHSEED": seed,
                # `src` is on pytest's path, not the interpreter's.
                "PYTHONPATH": str(pathlib.Path(__file__).parents[3] / "src"),
            },
        ).stdout.strip()
        for seed in ("0", "1")
    }

    assert digests == {plan_fingerprint(_plan())}


def test_casing_spacing_and_a_question_mark_are_not_part_of_the_question() -> None:
    """Plan §2.15's own example: two spellings of one question must not miss each other."""
    asked = _plan(normalized_query="Best national parks   for avoiding crowds?")

    assert plan_fingerprint(asked) == plan_fingerprint(_plan())


def test_criteria_order_does_not_change_the_key() -> None:
    """ "quiet, cheap" and "cheap, quiet" ask for the same thing."""
    reordered = _plan(criteria=["scenic", "uncrowded"])

    assert plan_fingerprint(reordered) == plan_fingerprint(_plan())


def test_a_repeated_criterion_does_not_change_the_key() -> None:
    assert plan_fingerprint(_plan(criteria=["uncrowded", "scenic", "Scenic"])) == plan_fingerprint(
        _plan()
    )


def test_a_different_scope_is_a_different_question() -> None:
    elsewhere = _plan(scope=GeoScope(type="country", value="Canada"))

    assert plan_fingerprint(elsewhere) != plan_fingerprint(_plan())


def test_a_different_granularity_is_a_different_question() -> None:
    coarser = _plan(entity_granularity=EntityType.STATE)

    assert plan_fingerprint(coarser) != plan_fingerprint(_plan())


def test_different_criteria_are_a_different_question() -> None:
    """A run counting *cheap* parks cannot answer for one counting *quiet* parks.

    The counts come from the same corpus and mean different things, which is
    exactly the wrong answer wearing a right answer's clothes.
    """
    cheaper = _plan(criteria=["cheap"])

    assert plan_fingerprint(cheaper) != plan_fingerprint(_plan())


def test_a_different_topic_is_a_different_question() -> None:
    assert plan_fingerprint(_plan(topic="hiking")) != plan_fingerprint(_plan())


def test_the_model_s_search_suggestions_are_not_part_of_the_key() -> None:
    """Discovery proposes different queries every run (§2.14.4).

    If those were in the key, the fingerprint would change on almost every
    run and nothing would ever hit — a feature that silently does nothing.
    """
    elsewhere = _plan(
        seed_queries=["underrated parks", "empty parks august"],
        candidate_subreddits=["Camping", "Hiking"],
    )

    assert plan_fingerprint(elsewhere) == plan_fingerprint(_plan())


def test_how_sure_the_model_was_is_not_part_of_the_key() -> None:
    """Confidence is a fact about the model that day, not about the question."""
    assert plan_fingerprint(_plan(granularity_confidence=0.71)) == plan_fingerprint(_plan())
