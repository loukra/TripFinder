"""Plan §10 Phase 13: clarify, cancel, evidence, and the widened /results guard.

``test_research_diagnostics_api.py`` and ``test_research_failure_api.py``
already cover ``source_unavailable``/``failed`` and the degraded-vs-thin
distinction; this file covers the endpoints and guard behavior Phase 13
adds on top of them.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import (
    ClarificationOption,
    ClarificationRequest,
    EntityType,
    GeoScope,
    GranularityConfidence,
    PendingPlan,
    Research,
    ResearchStatus,
    Result,
)
from tripfinder.jobs.repository import JobRepository
from tripfinder.persistence.repositories import ResearchRepository


async def _persist(
    session_factory: async_sessionmaker[AsyncSession], research: Research
) -> Research:
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    return research


def _awaiting_clarification(make_research: Callable[..., Research]) -> Research:
    research = make_research("most underrated US destinations for nature")
    research.status = ResearchStatus.NEEDS_CLARIFICATION
    research.clarification = ClarificationRequest(
        question="What kind of places are you looking for?",
        options=[
            ClarificationOption(label="States", entity_granularity=EntityType.STATE),
            ClarificationOption(
                label="National parks and natural areas", entity_granularity=EntityType.PARK
            ),
        ],
    )
    research.pending_plan = PendingPlan(
        normalized_query="most underrated us destinations for nature",
        scope=GeoScope(type="country", value="United States"),
        topic="nature",
        criteria=["underrated"],
        seed_queries=["underrated us nature"],
        candidate_subreddits=["travel"],
        granularity_candidates=[
            GranularityConfidence(entity_granularity=EntityType.STATE, confidence=0.5),
            GranularityConfidence(entity_granularity=EntityType.PARK, confidence=0.45),
        ],
    )
    return research


def _ranked_result(**overrides: object) -> Result:
    defaults: dict[str, object] = dict(
        entity_id="alaska",
        entity_name="Alaska",
        supporter_count=3,
        share=0.5,
        respondent_pool_size=6,
        discussion_count=2,
        weighted_score=3.0,
        confidence=0.9,
    )
    defaults.update(overrides)
    return Result(**defaults)  # type: ignore[arg-type]


class TestClarify:
    async def test_answering_moves_the_research_on_and_enqueues_a_job(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await _persist(session_factory, _awaiting_clarification(make_research))

        response = client.post(
            f"/api/research/{research.id}/clarify", json={"entity_granularity": "state"}
        )

        assert response.status_code == 200
        assert response.json() == {"id": str(research.id), "status": "discovering"}

        async with session_factory() as session:
            reloaded = await ResearchRepository(session).get(research.id)
            job = await JobRepository(session).get_for_research(research.id)

        assert reloaded is not None
        assert reloaded.status == ResearchStatus.DISCOVERING
        assert reloaded.resume_plan is not None
        assert reloaded.resume_plan.entity_granularity == EntityType.STATE
        assert reloaded.resume_plan.granularity_confidence == 0.5
        assert reloaded.normalized_query == "most underrated us destinations for nature"
        assert job is not None
        assert job.status == "pending"

    async def test_an_option_that_was_never_offered_is_rejected(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await _persist(session_factory, _awaiting_clarification(make_research))

        response = client.post(
            f"/api/research/{research.id}/clarify", json={"entity_granularity": "beach"}
        )

        assert response.status_code == 400

    async def test_clarifying_a_research_not_awaiting_it_is_rejected(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.COMPLETED
        await _persist(session_factory, research)

        response = client.post(
            f"/api/research/{research.id}/clarify", json={"entity_granularity": "state"}
        )

        assert response.status_code == 409

    async def test_unknown_research_id_is_404(self, client: TestClient) -> None:
        response = client.post(
            f"/api/research/{uuid4()}/clarify", json={"entity_granularity": "state"}
        )

        assert response.status_code == 404


class TestCancel:
    async def test_a_still_queued_job_is_cancelled_immediately(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await _persist(session_factory, make_research())
        async with session_factory() as session:
            await JobRepository(session).enqueue(research.id)

        response = client.post(f"/api/research/{research.id}/cancel")

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

        async with session_factory() as session:
            reloaded = await ResearchRepository(session).get(research.id)
            job = await JobRepository(session).get_for_research(research.id)
        assert reloaded is not None
        assert reloaded.status == ResearchStatus.CANCELLED
        assert job is not None
        assert job.status == "cancelled"

    async def test_a_research_paused_for_clarification_is_cancelled_immediately(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """No job is running while paused for clarification — nothing to flag, only cancel."""
        research = await _persist(session_factory, _awaiting_clarification(make_research))
        async with session_factory() as session:
            job_id = await JobRepository(session).enqueue(research.id)
            await JobRepository(session).mark_succeeded(job_id)

        response = client.post(f"/api/research/{research.id}/cancel")

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

    async def test_a_finished_research_cannot_be_cancelled(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.COMPLETED
        await _persist(session_factory, research)

        response = client.post(f"/api/research/{research.id}/cancel")

        assert response.status_code == 409

    async def test_unknown_research_id_is_404(self, client: TestClient) -> None:
        response = client.post(f"/api/research/{uuid4()}/cancel")

        assert response.status_code == 404


class TestEvidence:
    async def test_returns_paginated_permalinks_for_a_ranked_entity(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.COMPLETED
        research.results = [
            _ranked_result(
                evidence_permalinks=[
                    f"https://reddit.com/r/travel/comments/{i}" for i in range(5)
                ]
            )
        ]
        await _persist(session_factory, research)

        response = client.get(
            f"/api/research/{research.id}/evidence", params={"entity_id": "alaska", "limit": 2}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["entity_name"] == "Alaska"
        assert body["total"] == 5
        assert len(body["permalinks"]) == 2

    async def test_weak_results_are_searched_too(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.COMPLETED
        research.weak_results = [
            _ranked_result(
                entity_id="wyoming",
                entity_name="Wyoming",
                evidence_permalinks=["https://reddit.com/r/travel/comments/1"],
            )
        ]
        await _persist(session_factory, research)

        response = client.get(
            f"/api/research/{research.id}/evidence", params={"entity_id": "wyoming"}
        )

        assert response.status_code == 200
        assert response.json()["entity_name"] == "Wyoming"

    async def test_an_entity_id_not_in_this_research_is_404(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.COMPLETED
        await _persist(session_factory, research)

        response = client.get(
            f"/api/research/{research.id}/evidence", params={"entity_id": "nowhere"}
        )

        assert response.status_code == 404

    async def test_a_research_with_no_results_object_refuses_too(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.NEEDS_CLARIFICATION
        await _persist(session_factory, research)

        response = client.get(
            f"/api/research/{research.id}/evidence", params={"entity_id": "alaska"}
        )

        assert response.status_code == 409


class TestResultsGuardCoversEveryNonReadyStatus:
    """Before Phase 13, only ``source_unavailable``/``failed`` were guarded — everything
    else fell through to a misleading ``200`` with an empty results list."""

    async def test_rejected_has_no_results_object(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.REJECTED
        await _persist(session_factory, research)

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 409

    async def test_needs_clarification_has_no_results_object(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await _persist(session_factory, _awaiting_clarification(make_research))

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 409

    async def test_cancelled_has_no_results_object(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.CANCELLED
        await _persist(session_factory, research)

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 409

    async def test_still_running_has_no_results_object(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.DISCOVERING
        await _persist(session_factory, research)

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 409

    async def test_completed_partial_still_returns_its_results(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """The guard must not be so wide it catches statuses that do have a results page."""
        research = make_research()
        research.status = ResearchStatus.COMPLETED_PARTIAL
        research.results = [_ranked_result()]
        await _persist(session_factory, research)

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 200


class TestClarificationSurfacesOnTheStatusEndpoint:
    async def test_the_question_and_options_are_visible(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await _persist(session_factory, _awaiting_clarification(make_research))

        body = client.get(f"/api/research/{research.id}").json()

        assert body["clarification"]["question"]
        assert {opt["entity_granularity"] for opt in body["clarification"]["options"]} == {
            "state",
            "park",
        }

    async def test_clarification_is_hidden_once_the_research_has_moved_on(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.COMPLETED
        await _persist(session_factory, research)

        body = client.get(f"/api/research/{research.id}").json()

        assert body["clarification"] is None
