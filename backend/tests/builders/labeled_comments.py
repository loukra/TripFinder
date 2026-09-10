"""The labeled comment corpus for Phase 8 (plan §10, `PROJECT.md` §26 Phase 8).

Ten hand-written comments, two per label, answering *"Most underrated US
states for nature"*:

* ``clearly_relevant`` — names a state and recommends it outright;
* ``indirectly_relevant`` — recommends without ever framing it as an answer;
* ``irrelevant`` — substantive prose about something else entirely;
* ``ambiguous`` — a mixed stance, or a name two different places share;
* ``equivalent_wording`` — a real recommendation that shares **no** word
  with the query or with the state it recommends (*"the Beaver State"*).

That last pair is the acceptance criterion made concrete: any keyword filter
would drop them, and they are the comments a semantic analysis has to keep.

Each entry carries what a well-behaved model should say about it. Offline
tests use that to drive :class:`FakeLLMProvider` and assert what *our code*
does with an answer; the evaluation test (``-m evaluation``) throws the same
bodies at a real model and asserts the answer itself. Neither reads the
labels the other asserts on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import HttpUrl

from tripfinder.analysis.comment_analysis import (
    CommentAnalysis,
    CommentAnalysisBatch,
    EntityMention,
)
from tripfinder.domain.models import Comment, EntityType, Stance

FIXTURE = Path(__file__).parent.parent / "fixtures" / "comment_analysis" / "labeled_comments.json"

CREATED_AT = datetime(2026, 6, 1, tzinfo=UTC)


@dataclass(frozen=True)
class LabeledComment:
    """One fixture comment: its text, its label, and the answer it deserves."""

    id: str
    label: str
    user_id: str
    body: str
    quote: str | None
    raw_text: str | None
    entity: str | None
    entity_type: EntityType | None
    expect_relevant: bool
    expect_positive: bool
    expect_entities: tuple[str, ...]

    def as_comment(self, *, document_id: str = "d-polling") -> Comment:
        return Comment(
            id=self.id,
            source_document_id=document_id,
            user_id=self.user_id,
            body=self.body,
            created_at=CREATED_AT,
            permalink=HttpUrl(f"https://reddit.com/comments/{self.id}"),
        )

    def as_analysis(self) -> CommentAnalysis:
        """What a model that read this comment correctly would return for it."""
        return CommentAnalysis(
            comment_id=self.id,
            topic_relevance=0.9 if self.expect_relevant else 0.05,
            criterion_relevance=0.85 if self.expect_relevant else 0.05,
            scope_match=True,
            overall_confidence=0.5 if self.label == "ambiguous" else 0.9,
            mentions=self._mentions(),
            reasoning=f"labeled fixture: {self.label}",
        )

    def _mentions(self) -> list[EntityMention]:
        if self.entity is None or self.quote is None or self.raw_text is None:
            return []
        return [
            EntityMention(
                raw_text=self.raw_text,
                normalized_guess=self.entity,
                entity_type=self.entity_type or EntityType.OTHER,
                stance=Stance.POSITIVE if self.expect_positive else Stance.MIXED,
                strength=0.8 if self.expect_positive else 0.4,
                supporting_quote=self.quote,
            )
        ]


@cache
def labeled_query() -> str:
    return str(_load()["query"])


@cache
def labeled_comments() -> tuple[LabeledComment, ...]:
    """The whole corpus, in fixture order."""
    return tuple(
        LabeledComment(
            id=str(entry["id"]),
            label=str(entry["label"]),
            user_id=str(entry["user_id"]),
            body=str(entry["body"]),
            quote=entry["quote"],
            raw_text=entry["raw_text"],
            entity=entry["entity"],
            entity_type=EntityType(entry["entity_type"]) if entry["entity_type"] else None,
            expect_relevant=bool(entry["expect_relevant"]),
            expect_positive=bool(entry["expect_positive"]),
            expect_entities=tuple(entry["expect_entities"]),
        )
        for entry in _load()["comments"]
    )


def labeled(label: str) -> tuple[LabeledComment, ...]:
    """Every fixture carrying one label."""
    return tuple(entry for entry in labeled_comments() if entry.label == label)


def one(comment_id: str) -> LabeledComment:
    """A single fixture by id — raises rather than returning a default."""
    for entry in labeled_comments():
        if entry.id == comment_id:
            return entry
    raise LookupError(comment_id)


def expected_batch(entries: tuple[LabeledComment, ...] | None = None) -> CommentAnalysisBatch:
    """The response a well-behaved model would give for these fixtures."""
    return CommentAnalysisBatch(
        items=[entry.as_analysis() for entry in (entries or labeled_comments())]
    )


def _load() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FIXTURE.read_text())
    return loaded
