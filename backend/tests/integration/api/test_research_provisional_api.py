"""The provisional results contract (plan §2.13.3, §10 Phase 14.7).

A run that is still analysing now has a results object. Everything in this
file is about the one obligation that makes that safe: an unfinished
ranking must be impossible to mistake for a finished one — including by a
client that has never heard of the flag saying so.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tripfinder.api.messages import PROVISIONAL_MESSAGES, STATUS_MESSAGES
from tripfinder.domain.models import (
    Research,
    ResearchStatus,
    Result,
    SuppressionReason,
)
from tripfinder.persistence.repositories import ResearchRepository


async def _persist(
    session_factory: async_sessionmaker[AsyncSession], research: Research
) -> Research:
    async with session_factory() as session:
        await ResearchRepository(session).create(research)
    return research


def _result(name: str, supporters: int, *, pool: int) -> Result:
    return Result(
        entity_id=f"state:{name.lower()}",
        entity_name=name,
        supporter_count=supporters,
        share=supporters / pool,
        respondent_pool_size=pool,
        discussion_count=2,
        weighted_score=float(supporters),
        confidence=0.8,
    )


async def _analysing(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
    *,
    strong: list[Result] | None = None,
    weak: list[Result] | None = None,
) -> Research:
    """A run mid-analysis, with whatever its last snapshot produced."""
    research = make_research()
    research.status = ResearchStatus.ANALYZING
    research.results = strong if strong is not None else [_result("Alaska", 7, pool=20)]
    research.weak_results = weak if weak is not None else [_result("Vermont", 2, pool=20)]
    return await _persist(session_factory, research)


async def _completed(
    session_factory: async_sessionmaker[AsyncSession],
    make_research: Callable[..., Research],
) -> Research:
    research = make_research()
    research.status = ResearchStatus.COMPLETED
    research.results = [_result("Alaska", 7, pool=20)]
    research.weak_results = [_result("Vermont", 2, pool=20)]
    return await _persist(session_factory, research)


class TestARunStillAnalysingReportsWhatItHas:
    async def test_it_serves_a_ranked_result_instead_of_a_409(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await _analysing(session_factory, make_research)

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "analyzing"
        assert body["provisional"] is True
        assert [item["entity_name"] for item in body["results"]] == ["Alaska"]
        assert [item["supporter_count"] for item in body["results"]] == [7]

    async def test_the_weak_list_travels_with_it(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """Plan §2.13.1: nobody clears five supporters in the first wave, and
        §4.4 forbids padding the strong list to hide that. Without the weak
        list an early provisional response would be an empty page."""
        research = await _analysing(
            session_factory,
            make_research,
            strong=[],
            weak=[_result("Vermont", 2, pool=6), _result("Maine", 1, pool=6)],
        )

        body = client.get(f"/api/research/{research.id}/results").json()

        assert body["results"] == []
        assert [item["entity_name"] for item in body["weak_results"]] == ["Vermont", "Maine"]
        assert [item["supporter_count"] for item in body["weak_results"]] == [2, 1]

    async def test_a_run_that_has_not_snapshotted_yet_says_so_honestly(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """``analyzing`` is set by retrieval, before a single comment has been
        analysed, so there is a window with nothing in it. Provisional and
        empty is the honest description of that window."""
        research = await _analysing(session_factory, make_research, strong=[], weak=[])

        body = client.get(f"/api/research/{research.id}/results").json()

        assert body["provisional"] is True
        assert body["results"] == []
        assert body["weak_results"] == []


class TestAClientThatIgnoresTheFlag:
    """Plan §2.13.3's load-bearing requirement. A screenshot, a cached
    response or a naive consumer must not be able to render an unfinished
    ranking as a settled one."""

    async def test_every_share_is_null_never_zero(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = await _analysing(session_factory, make_research)

        body = client.get(f"/api/research/{research.id}/results").json()

        assert body["percentages_suppressed"] is True
        shares = [item["share"] for item in [*body["results"], *body["weak_results"]]]
        assert shares == [None, None]
        # A zero would be a number a naive client prints. A null is a hole.
        assert not any(share == 0 for share in shares)

    async def test_the_counts_themselves_are_unchanged(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """Counts only grow (plan §2.13.1), so they are shown as they are."""
        research = await _analysing(session_factory, make_research)

        body = client.get(f"/api/research/{research.id}/results").json()

        assert body["results"][0]["supporter_count"] == 7
        assert body["results"][0]["respondent_pool_size"] == 20

    async def test_a_finished_run_still_gets_its_percentages(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """The switch back is real information: the corpus closed."""
        research = await _completed(session_factory, make_research)

        body = client.get(f"/api/research/{research.id}/results").json()

        assert body["provisional"] is False
        assert body["percentages_suppressed"] is False
        assert body["results"][0]["share"] == 0.35

    async def test_a_provisional_and_a_finished_run_never_read_the_same(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """Plan §0.1 rule 4, applied to the unfinished case: identical
        evidence, different promise, and the two responses must not match."""
        provisional = await _analysing(session_factory, make_research)
        finished = await _completed(session_factory, make_research)

        early = client.get(f"/api/research/{provisional.id}/results").json()
        late = client.get(f"/api/research/{finished.id}/results").json()

        assert [item["supporter_count"] for item in early["results"]] == [
            item["supporter_count"] for item in late["results"]
        ]
        assert early["status"] != late["status"]
        assert early["message"] != late["message"]
        assert early["provisional"] != late["provisional"]
        assert early["results"][0]["share"] != late["results"][0]["share"]

    async def test_the_message_is_not_the_progress_flavor(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """The status endpoint answers *what is happening*; a results page
        has to answer *what do these numbers mean*."""
        research = await _analysing(session_factory, make_research)

        body = client.get(f"/api/research/{research.id}/results").json()

        assert body["message"] == PROVISIONAL_MESSAGES[ResearchStatus.ANALYZING]
        assert body["message"] != STATUS_MESSAGES[ResearchStatus.ANALYZING]


class TestThinBecauseItIsEarlyVersusThinBecauseEvidenceWasLost:
    """Plan §0.1, in the form this phase can breach it. Two runs, the same
    short list, different causes — and the payload has to tell them apart."""

    async def test_the_two_are_distinguishable_in_one_payload(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        early = await _analysing(
            session_factory, make_research, strong=[], weak=[_result("Vermont", 2, pool=6)]
        )

        lossy = make_research()
        lossy.status = ResearchStatus.ANALYZING
        lossy.weak_results = [_result("Vermont", 2, pool=6)]
        lossy.diagnostics.record_suppression(
            step="comment_analysis",
            reason=SuppressionReason.ANALYSIS_BATCH_FAILED,
            count=180,
            detail="comments in batches that failed outright (llm_unavailable x9)",
        )
        await _persist(session_factory, lossy)

        early_status = client.get(f"/api/research/{early.id}").json()
        lossy_status = client.get(f"/api/research/{lossy.id}").json()

        assert [s["reason"] for s in early_status["diagnostics"]["suppressions"]] == []
        assert (
            SuppressionReason.ANALYSIS_BATCH_FAILED.value,
            180,
        ) in [
            (s["reason"], s["count"]) for s in lossy_status["diagnostics"]["suppressions"]
        ]
        # Same ranking, so nothing in the results payload separates them —
        # which is exactly why the suppression record has to.
        early_results = client.get(f"/api/research/{early.id}/results").json()
        lossy_results = client.get(f"/api/research/{lossy.id}/results").json()
        assert early_results["weak_results"] == lossy_results["weak_results"]


class TestACancelledRunKeepsWhatItPaidFor:
    """Plan §2.13.3's one amendment to §7.1."""

    async def test_a_run_cancelled_mid_analysis_still_reports_its_evidence(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        research = make_research()
        research.status = ResearchStatus.CANCELLED
        research.results = [_result("Alaska", 7, pool=20)]
        await _persist(session_factory, research)

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 200
        body = response.json()
        assert body["provisional"] is True
        assert body["results"][0]["supporter_count"] == 7
        assert body["results"][0]["share"] is None
        assert body["message"] == PROVISIONAL_MESSAGES[ResearchStatus.CANCELLED]

    async def test_a_run_cancelled_before_it_analysed_anything_still_has_no_results(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """The rest of §7.1's "No" column is untouched: no snapshot, no page."""
        research = make_research()
        research.status = ResearchStatus.CANCELLED
        await _persist(session_factory, research)

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 409
        assert response.json()["detail"]["status"] == "cancelled"

    async def test_a_failed_run_is_not_given_one_by_the_same_door(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """A failed run's snapshots are cleared by the runner, and even with
        results present it keeps its §0.1 error: unfinished evidence and no
        evidence are different claims."""
        research = make_research()
        research.status = ResearchStatus.FAILED
        research.results = [_result("Alaska", 7, pool=20)]
        await _persist(session_factory, research)

        response = client.get(f"/api/research/{research.id}/results")

        assert response.status_code == 409
        assert response.json()["detail"]["status"] == "failed"


class TestEvidenceFollowsTheSameRule:
    async def test_evidence_is_available_for_a_provisional_entity(
        self,
        client: TestClient,
        session_factory: async_sessionmaker[AsyncSession],
        make_research: Callable[..., Research],
    ) -> None:
        """A provisional count the reader cannot check would be a number to
        take on trust, which is the one thing this product does not ask for."""
        research = make_research()
        research.status = ResearchStatus.ANALYZING
        result = _result("Alaska", 7, pool=20)
        result.evidence_permalinks = [HttpUrl("https://reddit.com/comments/c1")]
        research.results = [result]
        await _persist(session_factory, research)

        response = client.get(
            f"/api/research/{research.id}/evidence", params={"entity_id": result.entity_id}
        )

        assert response.status_code == 200
        assert response.json()["total"] == 1
