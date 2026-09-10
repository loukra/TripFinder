"""Plan §0.1, applied to the LLM: a broken model is not a quiet topic.

This is §2.7's regression wearing different clothes. A source outage was
made distinguishable from an absence of evidence in Phase 7; Phase 7.5 owes
the same guarantee for the model, because a run whose LLM calls fail for
want of a credential produces an empty analysis — and an empty analysis
looks exactly like a question nobody answered.

Every test runs a *real* pipeline step against the *real* OpenAI adapter,
with only the HTTP transport stubbed. Nothing here touches the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI

from builders.openai_responses import refusal_response_body, response_body
from tripfinder.ai.openai import OpenAIConfig, OpenAIProvider
from tripfinder.domain.models import (
    FailureKind,
    Research,
    ResearchStatus,
    Result,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.fake_pipeline import (
    build_fake_pipeline_context,
    build_fake_pipeline_runner,
)
from tripfinder.pipeline.runner import PipelineRunner
from tripfinder.pipeline.steps.query_understanding import QueryUnderstandingStep
from tripfinder.sources.fake.adapter import FakeSourceAdapter

QUERY = "most underrated US states for nature"


def _provider(handler: Callable[[httpx2.Request], httpx2.Response]) -> OpenAIProvider:
    config = OpenAIConfig(max_retries=0, timeout_seconds=5.0)
    client = AsyncOpenAI(
        api_key="test-key-not-a-real-credential",
        max_retries=config.max_retries,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return OpenAIProvider(config, client=client)


def _responding(status_code: int, body: dict[str, Any]) -> Callable[..., httpx2.Response]:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code, json=body)

    return handler


def _context(provider: OpenAIProvider) -> PipelineContext:
    research = Research(
        original_query=QUERY, created_at=datetime.now(UTC), status=ResearchStatus.PENDING
    )
    return PipelineContext(research=research, source=FakeSourceAdapter(), llm=provider)


async def _run_with(provider: OpenAIProvider) -> Research:
    """One real AI step, driven by the real adapter over a stubbed transport."""
    context = await PipelineRunner([QueryUnderstandingStep()]).run(_context(provider))
    return context.research


async def _run_with_no_credential() -> Research:
    return await _run_with(OpenAIProvider(OpenAIConfig(), api_key=None))


async def _run_with_a_rejected_credential() -> Research:
    return await _run_with(
        _provider(_responding(401, {"error": {"message": "Incorrect API key provided"}}))
    )


async def _thin_but_genuine_run() -> Research:
    """A healthy run that simply did not find much — the outcome to be told apart from.

    The fake pipeline is the only thing in the tree that produces results
    today, so it stands in for "we looked properly and this is what there
    was".
    """
    context = await build_fake_pipeline_runner().run(build_fake_pipeline_context(QUERY))
    return context.research


class TestAMissingOrRejectedCredentialFailsTheResearch:
    """Plan §10 Phase 7.5: named reason, and no results object."""

    async def test_a_missing_credential_fails_the_research(self) -> None:
        research = await _run_with_no_credential()

        assert research.status is ResearchStatus.FAILED

    async def test_a_rejected_credential_fails_the_research(self) -> None:
        research = await _run_with_a_rejected_credential()

        assert research.status is ResearchStatus.FAILED

    @pytest.mark.parametrize(
        "run",
        [_run_with_no_credential, _run_with_a_rejected_credential],
        ids=["missing", "rejected"],
    )
    async def test_the_failure_names_its_cause_and_its_step(
        self, run: Callable[[], Any]
    ) -> None:
        research = await run()

        failure = research.diagnostics.failure
        assert failure is not None
        assert failure.kind is FailureKind.LLM_CREDENTIAL
        assert failure.step == "query_understanding"
        assert failure.detail.strip()

    @pytest.mark.parametrize(
        "run",
        [_run_with_no_credential, _run_with_a_rejected_credential],
        ids=["missing", "rejected"],
    )
    async def test_there_is_no_results_object(self, run: Callable[[], Any]) -> None:
        research = await run()

        assert research.results == []

    async def test_the_detail_never_leaks_the_credential(self) -> None:
        research = await _run_with_a_rejected_credential()

        failure = research.diagnostics.failure
        assert failure is not None
        assert "test-key-not-a-real-credential" not in failure.detail

    async def test_a_provider_outage_is_a_different_kind_from_a_credential_problem(
        self,
    ) -> None:
        """Four kinds, four remedies — collapsing them would lose the reason."""
        research = await _run_with(
            _provider(_responding(503, {"error": {"message": "overloaded"}}))
        )

        failure = research.diagnostics.failure
        assert failure is not None
        assert failure.kind is FailureKind.LLM_UNAVAILABLE

    async def test_an_unusable_answer_is_a_failure_not_an_empty_finding(self) -> None:
        """A refusal must not become "nobody recommended anything"."""
        research = await _run_with(_responding_provider_refusal())

        failure = research.diagnostics.failure
        assert failure is not None
        assert failure.kind is FailureKind.LLM_INVALID_RESPONSE
        assert research.results == []


def _responding_provider_refusal() -> OpenAIProvider:
    return _provider(_responding(200, refusal_response_body()))


class TestASuppressedRunIsDistinguishableFromAThinOne:
    """The §0.1 rule-5 test: the two outcomes may never look alike.

    This is the regression that would otherwise reintroduce the bug — not
    "does the failure path work", but "can anyone downstream tell the
    difference".
    """

    async def test_the_statuses_differ(self) -> None:
        failed = await _run_with_no_credential()
        thin = await _thin_but_genuine_run()

        assert failed.status is ResearchStatus.FAILED
        assert thin.status is not ResearchStatus.FAILED

    async def test_only_the_failed_run_names_a_failure(self) -> None:
        failed = await _run_with_no_credential()
        thin = await _thin_but_genuine_run()

        assert failed.diagnostics.failure is not None
        assert thin.diagnostics.failure is None

    async def test_only_the_thin_run_has_evidence_behind_it(self) -> None:
        """The thin run found little. The failed run found *nothing*, and says so."""
        failed = await _run_with_no_credential()
        thin = await _thin_but_genuine_run()

        assert failed.results == []
        assert thin.results != []
        assert all(isinstance(result, Result) for result in thin.results)

    async def test_a_failed_run_never_reaches_a_completed_status(self) -> None:
        failed = await _run_with_no_credential()

        assert failed.status not in {
            ResearchStatus.COMPLETED,
            ResearchStatus.COMPLETED_PARTIAL,
            ResearchStatus.COMPLETED_DEGRADED,
        }


class TestTheFailureStopsTheRunImmediately:
    async def test_no_later_step_runs_after_a_provider_failure(self) -> None:
        """Plan §7: a terminated research must not go on building output."""
        later = _RecordingStep()
        provider = OpenAIProvider(OpenAIConfig(), api_key=None)
        runner = PipelineRunner([QueryUnderstandingStep(), later])

        await runner.run(_context(provider))

        assert later.ran is False

    async def test_the_failing_step_still_records_its_progress_event(self) -> None:
        """Progress must show where the run stopped, not end silently."""
        provider = OpenAIProvider(OpenAIConfig(), api_key=None)
        context = await PipelineRunner([QueryUnderstandingStep()]).run(_context(provider))

        assert [event.step_name for event in context.progress] == ["query_understanding"]
        assert context.progress[-1].status is ResearchStatus.FAILED


class _RecordingStep:
    name = "later"

    def __init__(self) -> None:
        self.ran = False

    async def run(self, context: PipelineContext) -> PipelineContext:
        self.ran = True
        return context


class TestASuccessfulCallStillWorksThroughTheRealAdapter:
    """The control: the same wiring, with the model answering, does not fail."""

    async def test_a_valid_answer_produces_a_plan_and_no_failure(self) -> None:
        answer = {
            "is_travel_recommendation_query": True,
            "rejection_reason": None,
            "normalized_query": "underrated US states for nature",
            "scope": {"type": "country", "value": "United States"},
            "topic": "nature",
            "criteria": ["underrated"],
            "granularity_candidates": [{"entity_granularity": "state", "confidence": 0.95}],
            "seed_queries": ["underrated states nature"],
            "candidate_subreddits": ["travel"],
        }
        research = await _run_with(_provider(_responding(200, response_body(answer))))

        assert research.status is ResearchStatus.DISCOVERING
        assert research.diagnostics.failure is None
        assert research.normalized_query == "underrated US states for nature"

    async def test_the_prompt_actually_reached_the_provider(self) -> None:
        seen: list[httpx2.Request] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(request)
            return httpx2.Response(401, json={"error": {"message": "nope"}})

        await _run_with(_provider(handler))

        assert QUERY in json.loads(seen[0].content)["input"]
