"""What the API promises about a run the model broke (plan §0.1, §7.1, §10 Phase 7.5).

The companion to ``test_research_diagnostics_api.py``. That file proves a
source outage cannot reach the user looking like an absence of evidence;
this one proves the same of an LLM failure, which Phase 7.5 made reachable
for the first time.

Every test asks one question: can the caller tell a broken run from a quiet
one?
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.api.messages import FAILURE_MESSAGES
from tripfinder.domain.models import (
    FailureKind,
    Research,
    ResearchStatus,
    Result,
)
from tripfinder.persistence.repositories import ResearchRepository

CREDENTIAL_DETAIL = (
    "no OpenAI API key is configured, so no model call can be made "
    "(set OPENAI_API_KEY, or LLM_PROVIDER=fake)"
)


async def _persist(
    session_factory: async_sessionmaker[AsyncSession], research: Research
) -> Research:
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    return research


def _failed_on_the_credential(make_research: Callable[..., Research]) -> Research:
    research = make_research()
    research.status = ResearchStatus.FAILED
    research.diagnostics.record_failure(
        kind=FailureKind.LLM_CREDENTIAL,
        step="query_understanding",
        detail=CREDENTIAL_DETAIL,
    )
    research.results = []
    return research


def _thin_but_genuine(make_research: Callable[..., Research]) -> Research:
    """A healthy run that found two strong recommendations — §8.1 rule 3."""
    research = make_research()
    research.status = ResearchStatus.COMPLETED
    research.results = [
        Result(
            entity_id="alaska",
            entity_name="Alaska",
            supporter_count=7,
            share=7 / 12,
            respondent_pool_size=12,
            discussion_count=3,
            weighted_score=7.0,
            confidence=0.9,
        )
    ]
    return research


class TestAFailedRunIsExposedWithItsCause:
    """Plan §0.1 rule 2: the reason reaches the API, not just the logs."""

    async def test_the_status_endpoint_returns_the_named_failure(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await _persist(session_factory, _failed_on_the_credential(make_research))

        body = client.get(f"/api/research/{research.id}").json()

        assert body["status"] == ResearchStatus.FAILED
        assert body["diagnostics"]["failure"]["kind"] == FailureKind.LLM_CREDENTIAL
        assert body["diagnostics"]["failure"]["step"] == "query_understanding"
        assert body["diagnostics"]["failure"]["detail"] == CREDENTIAL_DETAIL

    async def test_the_status_message_names_the_cause_not_a_generic_fault(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await _persist(session_factory, _failed_on_the_credential(make_research))

        body = client.get(f"/api/research/{research.id}").json()

        assert body["message"] == FAILURE_MESSAGES[FailureKind.LLM_CREDENTIAL]
        assert "Something went wrong" not in body["message"]

    async def test_the_results_endpoint_refuses_to_return_a_results_object(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """§7.1: a failed run has no results page — not an empty one, none."""
        research = await _persist(session_factory, _failed_on_the_credential(make_research))

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 409
        assert "results" not in response.json()["detail"]

    async def test_the_refusal_is_machine_readable_and_names_the_failure(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await _persist(session_factory, _failed_on_the_credential(make_research))

        detail = client.get(f"/api/research/{research.id}/results").json()["detail"]

        assert detail["status"] == ResearchStatus.FAILED
        assert detail["failure"]["kind"] == FailureKind.LLM_CREDENTIAL
        assert detail["message"] == FAILURE_MESSAGES[FailureKind.LLM_CREDENTIAL]

    async def test_the_persisted_failure_survives_a_round_trip(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """Plan §0.1 rule 1: counts and reasons *persisted* in the snapshot."""
        research = await _persist(session_factory, _failed_on_the_credential(make_research))

        async with session_factory() as session:
            reloaded = await ResearchRepository(session).get(research.id)

        assert reloaded is not None
        assert reloaded.diagnostics.failure is not None
        assert reloaded.diagnostics.failure.kind is FailureKind.LLM_CREDENTIAL


class TestABrokenRunIsNeverMistakenForAQuietOne:
    """The §0.1 rule-5 regression, at the boundary the user actually reads."""

    async def test_the_two_runs_report_different_statuses_and_messages(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        failed = await _persist(session_factory, _failed_on_the_credential(make_research))
        thin = await _persist(session_factory, _thin_but_genuine(make_research))

        failed_body = client.get(f"/api/research/{failed.id}").json()
        thin_body = client.get(f"/api/research/{thin.id}").json()

        assert failed_body["status"] != thin_body["status"]
        assert failed_body["message"] != thin_body["message"]

    async def test_only_the_broken_run_carries_a_failure(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        failed = await _persist(session_factory, _failed_on_the_credential(make_research))
        thin = await _persist(session_factory, _thin_but_genuine(make_research))

        failed_body = client.get(f"/api/research/{failed.id}").json()
        thin_body = client.get(f"/api/research/{thin.id}").json()

        assert failed_body["diagnostics"]["failure"] is not None
        assert thin_body["diagnostics"]["failure"] is None

    async def test_only_the_thin_run_gets_a_results_page_at_all(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """The distinction that matters: two results is a finding, no results object is not."""
        failed = await _persist(session_factory, _failed_on_the_credential(make_research))
        thin = await _persist(session_factory, _thin_but_genuine(make_research))

        failed_response = client.get(f"/api/research/{failed.id}/results")
        thin_response = client.get(f"/api/research/{thin.id}/results")

        assert failed_response.status_code == 409
        assert thin_response.status_code == 200
        assert thin_response.json()["results"] != []

    async def test_the_thin_run_is_never_described_as_broken(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        thin = await _persist(session_factory, _thin_but_genuine(make_research))

        body = client.get(f"/api/research/{thin.id}").json()

        assert body["message"] not in FAILURE_MESSAGES.values()
