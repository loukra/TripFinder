"""What the API promises about a run it could not complete honestly (plan §8.1, §0.1).

The regression this file exists for is §2.7: a source outage and a genuine
absence of evidence must never reach the user looking the same. Every test
here is a way of asking "can the caller tell these two apart?"
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.domain.models import (
    Research,
    ResearchFlag,
    ResearchStatus,
    Result,
    SourceHealth,
    SourceOutcome,
    SuppressionReason,
    TriageDecidedBy,
    TriageDecision,
    TriageVerdict,
)
from tripfinder.persistence.repositories import ResearchRepository


def _thin_results() -> list[Result]:
    """Two strong recommendations — the shape of a genuinely thin finding."""
    return [
        Result(
            entity_id=entity_id,
            entity_name=name,
            supporter_count=supporters,
            share=supporters / 12,
            respondent_pool_size=12,
            discussion_count=3,
            weighted_score=float(supporters),
            confidence=0.9,
        )
        for entity_id, name, supporters in (("alaska", "Alaska", 7), ("oregon", "Oregon", 5))
    ]


async def _persist(
    session_factory: async_sessionmaker[AsyncSession],
    research: Research,
) -> Research:
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    return research


class TestSourceUnavailable:
    """§8.1 rule 1 — no results object at all."""

    async def test_the_results_endpoint_refuses_to_return_a_results_object(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.SOURCE_UNAVAILABLE
        research.diagnostics.source_outcome = SourceOutcome.UNAVAILABLE
        research.diagnostics.source_health = [
            SourceHealth(
                adapter="arctic_shift",
                calls_attempted=4,
                calls_succeeded=0,
                calls_failed=4,
                failure_kinds={"timeout": 3, "http_5xx": 1},
                success_rate=0.0,
            )
        ]
        await _persist(session_factory, research)

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "results" not in detail

    async def test_the_error_names_the_adapters_and_their_failure_kinds(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.SOURCE_UNAVAILABLE
        research.diagnostics.source_health = [
            SourceHealth(
                adapter="arctic_shift",
                calls_attempted=4,
                calls_succeeded=0,
                calls_failed=4,
                failure_kinds={"timeout": 3, "http_5xx": 1},
                success_rate=0.0,
            )
        ]
        await _persist(session_factory, research)

        detail = client.get(f"/api/research/{research.id}/results").json()["detail"]

        (adapter,) = detail["adapters"]
        assert adapter["adapter"] == "arctic_shift"
        assert adapter["failure_kinds"] == {"timeout": 3, "http_5xx": 1}
        assert "no evidence" in detail["message"]


class TestDegradedVersusThin:
    """The §2.7 regression, end to end through the API."""

    async def _degraded(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> Research:
        research = make_research("underrated US nature destinations")
        research.status = ResearchStatus.COMPLETED_DEGRADED
        research.results = _thin_results()
        research.diagnostics.source_outcome = SourceOutcome.DEGRADED
        research.diagnostics.source_health = [
            SourceHealth(
                adapter="arctic_shift",
                calls_attempted=10,
                calls_succeeded=5,
                calls_failed=5,
                failure_kinds={"timeout": 5},
                success_rate=0.5,
            )
        ]
        return await _persist(session_factory, research)

    async def _thin(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> Research:
        research = make_research("underrated US nature destinations")
        research.status = ResearchStatus.COMPLETED
        research.results = _thin_results()
        research.diagnostics.source_outcome = SourceOutcome.HEALTHY
        research.diagnostics.source_health = [
            SourceHealth(
                adapter="arctic_shift",
                calls_attempted=10,
                calls_succeeded=10,
                calls_failed=0,
                success_rate=1.0,
            )
        ]
        return await _persist(session_factory, research)

    async def test_a_degraded_run_suppresses_percentages_but_keeps_counts(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await self._degraded(session_factory, make_research)

        body = client.get(f"/api/research/{research.id}/results").json()

        assert body["percentages_suppressed"] is True
        assert [item["share"] for item in body["results"]] == [None, None]
        assert [item["supporter_count"] for item in body["results"]] == [7, 5]

    async def test_a_healthy_thin_run_keeps_its_percentages(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await self._thin(session_factory, make_research)

        body = client.get(f"/api/research/{research.id}/results").json()

        assert body["percentages_suppressed"] is False
        assert body["results"][0]["share"] > 0

    async def test_the_two_runs_never_produce_the_same_user_facing_message(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """Identical evidence, different cause — and the responses must not match.

        This is the regression that would otherwise reintroduce §2.7: both
        runs carry the same two results, so nothing but the status, the
        message and the suppressed percentages distinguishes them.
        """
        degraded = await self._degraded(session_factory, make_research)
        thin = await self._thin(session_factory, make_research)

        degraded_body = client.get(f"/api/research/{degraded.id}/results").json()
        thin_body = client.get(f"/api/research/{thin.id}/results").json()

        assert [item["supporter_count"] for item in degraded_body["results"]] == [
            item["supporter_count"] for item in thin_body["results"]
        ]
        assert degraded_body["status"] != thin_body["status"]
        assert degraded_body["message"] != thin_body["message"]
        assert degraded_body["percentages_suppressed"] != thin_body["percentages_suppressed"]

    async def test_the_status_endpoint_also_distinguishes_them(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        degraded = await self._degraded(session_factory, make_research)
        thin = await self._thin(session_factory, make_research)

        degraded_body = client.get(f"/api/research/{degraded.id}").json()
        thin_body = client.get(f"/api/research/{thin.id}").json()

        assert degraded_body["diagnostics"]["source_outcome"] == "degraded"
        assert thin_body["diagnostics"]["source_outcome"] == "healthy"
        assert degraded_body["message"] != thin_body["message"]


class TestDiagnosticsAreExposed:
    """Plan §0.1 rule 2 — suppression counts reach the API, not just the logs."""

    async def test_suppressions_triage_verdicts_and_flags_are_all_visible(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.COMPLETED
        research.diagnostics.triage_decisions = [
            TriageDecision(
                document_id="d1",
                verdict=TriageVerdict.TOPICAL,
                reason="title names Alaska at the target granularity",
                confidence=1.0,
                decided_by=TriageDecidedBy.RULE,
            )
        ]
        research.diagnostics.record_suppression(
            step="document_triage", reason=SuppressionReason.TRIAGE_EXCLUDED, count=12
        )
        research.diagnostics.raise_flag(ResearchFlag.LOW_POLLING_DOCUMENT_RATIO)
        await _persist(session_factory, research)

        diagnostics = client.get(f"/api/research/{research.id}").json()["diagnostics"]

        (suppression,) = diagnostics["suppressions"]
        assert (suppression["reason"], suppression["count"]) == ("triage_excluded", 12)
        assert diagnostics["flags"] == ["low_polling_document_ratio"]
        assert diagnostics["triage_decisions"][0]["reason"].startswith("title names Alaska")

    async def test_a_thin_result_can_always_name_its_cause(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """Plan §0.1 rule 3 — a short result set is attributable, not mysterious."""
        research = make_research()
        research.status = ResearchStatus.COMPLETED
        research.results = _thin_results()[:1]
        research.diagnostics.record_suppression(
            step="document_triage",
            reason=SuppressionReason.TRIAGE_NOT_POLLING,
            count=40,
            detail="leading title naming the entity",
        )
        await _persist(session_factory, research)

        diagnostics = client.get(f"/api/research/{research.id}").json()["diagnostics"]

        assert diagnostics["suppressions"][0]["count"] == 40
        assert diagnostics["suppressions"][0]["detail"] == "leading title naming the entity"
