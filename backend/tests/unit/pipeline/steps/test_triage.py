"""Document Triage (plan §4.6 step 4, §4.7).

The acceptance criteria covered here, in plan order: deterministic
pre-checks short-circuit before any AI call; leading titles naming an
entity classify as topical and open questions as polling; scope,
granularity and criterion mismatches are each caught by a fixture;
low-confidence documents downgrade to topical and are never promoted to
polling; and verdicts and reasons are persisted.

That triage runs *before* retrieval — no comment tree fetched for an
excluded document — is asserted in ``test_retrieval.py``, where the fetches
actually happen.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from builders.phase7 import NOW, make_context, make_document
from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.analysis.aliases import StaticAliasTable
from tripfinder.analysis.triage import DocumentTriage, DocumentTriageBatch
from tripfinder.domain.config import ResearchBudget, ResearchConfig, TriageFloors
from tripfinder.domain.models import (
    ContextType,
    EntityType,
    ResearchFlag,
    ResearchStatus,
    SuppressionReason,
    TriageDecidedBy,
    TriageDecision,
    TriageVerdict,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.steps.triage import DocumentTriageStep

QUIET_TITLE = "Looking for somewhere quiet next spring"

ALIASES = StaticAliasTable({EntityType.STATE: ["Alaska", "Oregon", "Michigan"]})


class CountingLLM:
    """Wraps a provider and counts the structured calls it received."""

    def __init__(self, inner: FakeLLMProvider | None = None) -> None:
        self._inner = inner or FakeLLMProvider()
        self.calls = 0
        self.last_prompt = ""

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        self.calls += 1
        self.last_prompt = prompt
        return await self._inner.complete_structured(prompt=prompt, response_model=response_model)


def _ai(
    document_id: str,
    *,
    verdict: TriageVerdict = TriageVerdict.POLLING,
    scope: bool = True,
    granularity: bool = True,
    criterion: bool = True,
    confidence: float = 0.9,
    reason: str = "an open question about the target tier",
) -> DocumentTriage:
    return DocumentTriage(
        document_id=document_id,
        verdict=verdict,
        scope_match=scope,
        granularity_match=granularity,
        criterion_match=criterion,
        confidence=confidence,
        reason=reason,
    )


def _batch(*items: DocumentTriage) -> FakeLLMProvider:
    return FakeLLMProvider({DocumentTriageBatch: DocumentTriageBatch(items=list(items))})


def _step(**kwargs: int) -> DocumentTriageStep:
    return DocumentTriageStep(ALIASES, now=NOW, **kwargs)


def _decision(context: PipelineContext, document_id: str) -> TriageDecision:
    (found,) = [
        decision
        for decision in context.research.diagnostics.triage_decisions
        if decision.document_id == document_id
    ]
    return found


class TestDeterministicPreChecks:
    """Plan §4.7: these short-circuit before any AI call."""

    async def test_too_few_comments_is_excluded_without_an_ai_call(self) -> None:
        llm = CountingLLM()
        context = make_context(llm=llm)
        context.data["documents"] = [make_document("d1", comment_count=4)]

        await _step().run(context)

        assert llm.calls == 0
        decision = _decision(context, "d1")
        assert decision.verdict is TriageVerdict.EXCLUDE
        assert decision.decided_by is TriageDecidedBy.RULE

    async def test_a_document_beyond_the_age_limit_is_excluded_without_an_ai_call(self) -> None:
        llm = CountingLLM()
        context = make_context(llm=llm)
        context.data["documents"] = [make_document("d1", age_years=16)]

        await _step().run(context)

        assert llm.calls == 0
        assert _decision(context, "d1").verdict is TriageVerdict.EXCLUDE

    async def test_a_leading_title_naming_an_entity_is_topical_without_an_ai_call(self) -> None:
        llm = CountingLLM()
        context = make_context(llm=llm)
        context.data["documents"] = [make_document("d1", title="Alaska is underrated, right?")]

        await _step().run(context)

        assert llm.calls == 0
        decision = _decision(context, "d1")
        assert decision.verdict is TriageVerdict.TOPICAL
        assert "Alaska" in decision.reason

    async def test_a_statement_naming_an_entity_is_topical_too(self) -> None:
        context = make_context(llm=CountingLLM())
        context.data["documents"] = [
            make_document("d1", title="Just got back from Alaska - photos")
        ]

        await _step().run(context)

        assert _decision(context, "d1").verdict is TriageVerdict.TOPICAL

    async def test_an_open_question_naming_no_entity_is_polling_without_an_ai_call(self) -> None:
        llm = CountingLLM()
        context = make_context(llm=llm)
        context.data["documents"] = [make_document("d1", title="Most underrated state?")]

        await _step().run(context)

        assert llm.calls == 0
        assert _decision(context, "d1").verdict is TriageVerdict.POLLING

    async def test_an_alias_table_that_does_not_cover_the_tier_defers_to_the_model(self) -> None:
        """An empty table cannot tell "names nothing" from "we know nothing" (plan §4.7)."""
        llm = CountingLLM(_batch(_ai("d1")))
        context = make_context(llm=llm)
        context.data["documents"] = [make_document("d1", title="Alaska is underrated, right?")]

        await DocumentTriageStep(StaticAliasTable(), now=NOW).run(context)

        assert llm.calls == 1

    async def test_only_undecided_documents_reach_the_model(self) -> None:
        llm = CountingLLM(_batch(_ai("d3")))
        context = make_context(llm=llm)
        context.data["documents"] = [
            make_document("d1", comment_count=1),
            make_document("d2", title="Alaska is great"),
            make_document("d3", title="Somewhere quiet with good hiking"),
        ]

        await _step().run(context)

        assert llm.calls == 1
        assert _decision(context, "d3").decided_by is TriageDecidedBy.AI


class TestAiClassification:
    async def test_scope_mismatch_downgrades_polling_to_topical(self) -> None:
        context = make_context(llm=_batch(_ai("d1", scope=False)))
        context.data["documents"] = [make_document("d1", title=QUIET_TITLE)]

        await _step().run(context)

        decision = _decision(context, "d1")
        assert decision.verdict is TriageVerdict.TOPICAL
        assert "scope" in decision.reason

    async def test_granularity_mismatch_downgrades_polling_to_topical(self) -> None:
        context = make_context(llm=_batch(_ai("d1", granularity=False)))
        context.data["documents"] = [make_document("d1", title=QUIET_TITLE)]

        await _step().run(context)

        decision = _decision(context, "d1")
        assert decision.verdict is TriageVerdict.TOPICAL
        assert "granularity" in decision.reason

    async def test_criterion_mismatch_downgrades_rather_than_excludes(self) -> None:
        """It still holds real opinions; they just do not answer this question (§4.7)."""
        context = make_context(llm=_batch(_ai("d1", criterion=False)))
        context.data["documents"] = [make_document("d1", title=QUIET_TITLE)]

        await _step().run(context)

        assert _decision(context, "d1").verdict is TriageVerdict.TOPICAL
        assert [document.id for document in context.data["topical_documents"]] == ["d1"]

    async def test_low_confidence_downgrades_polling_to_topical(self) -> None:
        context = make_context(llm=_batch(_ai("d1", confidence=0.5)))
        context.data["documents"] = [make_document("d1", title=QUIET_TITLE)]

        await _step().run(context)

        decision = _decision(context, "d1")
        assert decision.verdict is TriageVerdict.TOPICAL
        assert decision.downgraded_for_low_confidence is True

    @pytest.mark.parametrize("confidence", [0.0, 0.3, 0.59])
    async def test_low_confidence_is_never_promoted_to_polling(self, confidence: float) -> None:
        """The §4.7 invariant, from either direction."""
        context = make_context(
            llm=_batch(
                _ai("d1", verdict=TriageVerdict.POLLING, confidence=confidence),
                _ai("d2", verdict=TriageVerdict.EXCLUDE, confidence=confidence),
            )
        )
        context.data["documents"] = [
            make_document("d1", title=QUIET_TITLE),
            make_document("d2", title="Anything worth seeing on the drive"),
        ]

        await _step().run(context)

        assert {
            decision.document_id: decision.verdict
            for decision in context.research.diagnostics.triage_decisions
        } == {"d1": TriageVerdict.TOPICAL, "d2": TriageVerdict.TOPICAL}

    async def test_the_confidence_threshold_is_configurable(self) -> None:
        config = ResearchConfig(triage_floors=TriageFloors(triage_confidence_threshold=0.4))
        context = make_context(llm=_batch(_ai("d1", confidence=0.5)), config=config)
        context.data["documents"] = [make_document("d1", title=QUIET_TITLE)]

        await _step().run(context)

        assert _decision(context, "d1").verdict is TriageVerdict.POLLING

    async def test_a_confident_exclude_is_honored(self) -> None:
        context = make_context(
            llm=_batch(_ai("d1", verdict=TriageVerdict.EXCLUDE, confidence=0.95))
        )
        context.data["documents"] = [make_document("d1", title="Selling my camper van")]

        await _step().run(context)

        assert _decision(context, "d1").verdict is TriageVerdict.EXCLUDE
        assert context.data["polling_documents"] == []
        assert context.data["topical_documents"] == []

    async def test_a_document_the_model_skipped_becomes_topical_and_is_recorded(self) -> None:
        """Silence is not permission (plan §0.1)."""
        context = make_context(llm=_batch())
        context.data["documents"] = [make_document("d1", title=QUIET_TITLE)]

        await _step().run(context)

        assert _decision(context, "d1").verdict is TriageVerdict.TOPICAL
        assert any(
            suppression.reason is SuppressionReason.TRIAGE_NO_VERDICT
            for suppression in context.research.diagnostics.suppressions
        )

    async def test_documents_are_classified_in_batches(self) -> None:
        llm = CountingLLM(
            FakeLLMProvider(
                {
                    DocumentTriageBatch: [
                        DocumentTriageBatch(items=[_ai("d0"), _ai("d1")]),
                        DocumentTriageBatch(items=[_ai("d2")]),
                    ]
                }
            )
        )
        context = make_context(llm=llm)
        context.data["documents"] = [
            make_document(f"d{index}", title=f"Somewhere quiet number {index}")
            for index in range(3)
        ]

        await _step(batch_size=2).run(context)

        assert llm.calls == 2
        assert len(context.data["polling_documents"]) == 3

    async def test_the_prompt_carries_only_discovery_metadata(self) -> None:
        """Triage sees titles, never comment bodies — it runs before retrieval."""
        llm = CountingLLM(_batch(_ai("d1")))
        context = make_context(llm=llm)
        context.data["documents"] = [
            make_document("d1", title=QUIET_TITLE, comment_count=42)
        ]

        await _step().run(context)

        assert QUIET_TITLE in llm.last_prompt
        assert "comments: 42" in llm.last_prompt


class TestOutputAndAccounting:
    def _mixed_corpus(self) -> list[object]:
        return [
            make_document("poll", title="Most underrated state?"),
            make_document("top", title="Oregon is underrated"),
            make_document("gone", comment_count=1),
        ]

    async def test_documents_are_split_and_tagged_by_context_type(self) -> None:
        context = make_context()
        context.data["documents"] = self._mixed_corpus()

        await _step().run(context)

        assert [d.id for d in context.data["polling_documents"]] == ["poll"]
        assert [d.id for d in context.data["topical_documents"]] == ["top"]
        assert context.data["polling_documents"][0].context_type is ContextType.POLLING
        assert context.data["topical_documents"][0].context_type is ContextType.TOPICAL

    async def test_every_verdict_is_persisted_with_its_reason(self) -> None:
        """Plan §4.7 mitigation 1 — a thin result is always explainable."""
        context = make_context()
        context.data["documents"] = self._mixed_corpus()

        await _step().run(context)

        decisions = context.research.diagnostics.triage_decisions
        assert [decision.document_id for decision in decisions] == ["poll", "top", "gone"]
        assert all(decision.reason.strip() for decision in decisions)

    async def test_the_triage_breakdown_reaches_statistics(self) -> None:
        """Plan §4.7 mitigation 2 — the breakdown is recorded, and the API exposes it."""
        context = make_context()
        context.data["documents"] = self._mixed_corpus()

        await _step().run(context)

        assert context.research.statistics == {
            "documents_triaged": 3,
            "documents_polling": 1,
            "documents_topical": 1,
            "documents_excluded": 1,
        }

    async def test_dropping_a_document_is_recorded_as_a_suppression(self) -> None:
        context = make_context()
        context.data["documents"] = self._mixed_corpus()

        await _step().run(context)

        assert {
            suppression.reason for suppression in context.research.diagnostics.suppressions
        } == {SuppressionReason.TRIAGE_NOT_POLLING, SuppressionReason.TRIAGE_EXCLUDED}

    async def test_a_low_polling_share_raises_a_flag(self) -> None:
        """Plan §4.7 mitigation 3 — below the ratio, the research is flagged."""
        context = make_context()
        context.data["documents"] = [
            make_document(f"top{index}", title="Oregon is underrated") for index in range(9)
        ] + [make_document("poll", title="Most underrated state?")]

        await _step().run(context)

        assert ResearchFlag.LOW_POLLING_DOCUMENT_RATIO in context.research.diagnostics.flags

    async def test_a_healthy_polling_share_raises_no_flag(self) -> None:
        context = make_context()
        context.data["documents"] = [
            make_document("poll", title="Most underrated state?"),
            make_document("top", title="Oregon is underrated"),
        ]

        await _step().run(context)

        assert context.research.diagnostics.flags == []

    async def test_the_polling_ratio_threshold_is_configurable(self) -> None:
        config = ResearchConfig(triage_floors=TriageFloors(min_polling_document_ratio=0.9))
        context = make_context(config=config)
        context.data["documents"] = [
            make_document("poll", title="Most underrated state?"),
            make_document("top", title="Oregon is underrated"),
        ]

        await _step().run(context)

        assert ResearchFlag.LOW_POLLING_DOCUMENT_RATIO in context.research.diagnostics.flags

    async def test_max_total_posts_is_enforced_before_classification(self) -> None:
        """Triage is where the corpus is capped — before it pays to classify it."""
        config = ResearchConfig(budget=ResearchBudget(max_total_posts=2))
        context = make_context(config=config)
        context.data["documents"] = [
            make_document(f"d{index}", title="Most underrated state?") for index in range(5)
        ]

        await _step().run(context)

        assert context.research.statistics["documents_triaged"] == 2
        (suppression,) = [
            entry
            for entry in context.research.diagnostics.suppressions
            if entry.reason is SuppressionReason.BUDGET_MAX_TOTAL_POSTS
        ]
        assert suppression.count == 3
        assert ResearchFlag.BUDGET_LIMIT_REACHED in context.research.diagnostics.flags

    async def test_the_step_advances_the_research_to_retrieving(self) -> None:
        context = make_context(status=ResearchStatus.DISCOVERING)
        context.data["documents"] = [make_document("poll", title="Most underrated state?")]

        await _step().run(context)

        assert context.research.status is ResearchStatus.RETRIEVING

    async def test_a_discovery_that_found_nothing_triages_cleanly(self) -> None:
        context = make_context()
        context.data["documents"] = []

        await _step().run(context)

        assert context.data["polling_documents"] == []
        assert context.research.diagnostics.flags == []
