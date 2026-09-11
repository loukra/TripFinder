"""Agentic Source Discovery over web search (plan §4.6 step 3, §2.11).

Two things are being tested, and they fail differently: the *loop* must stay
inside its budget however the LLM behaves, and the *hydration* must turn
addresses into documents without ever letting an outage look like a quiet
topic (plan §0.1).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, HttpUrl

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.analysis.discovery import DiscoveryTurnResponse
from tripfinder.domain.config import ResearchBudget, ResearchConfig, SourceHealthFloors
from tripfinder.domain.models import (
    Comment,
    EntityType,
    GeoScope,
    Research,
    ResearchPlan,
    ResearchStatus,
    SourceDocument,
    SourceOutcome,
)
from tripfinder.domain.ports import (
    LLMProvider,
    SourceAdapter,
    WebSearchHit,
    WebSearchProvider,
    WebSearchQuery,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.health import assess_source_health, get_recorder, terminal_status
from tripfinder.pipeline.steps.discovery import AgenticDiscoveryStep

THREAD_URL = "https://www.reddit.com/r/travel/comments/{post_id}/a_thread_title/"


def _plan() -> ResearchPlan:
    return ResearchPlan(
        normalized_query="underrated us states for nature",
        scope=GeoScope(type="country", value="United States"),
        entity_granularity=EntityType.STATE,
        granularity_confidence=0.9,
        topic="nature",
        criteria=["underrated"],
        seed_queries=["underrated states nature"],
        candidate_subreddits=["travel"],
    )


def _document(document_id: str) -> SourceDocument:
    return SourceDocument(
        id=document_id,
        source="fake",
        title=f"Document {document_id}",
        url=HttpUrl(THREAD_URL.format(post_id=document_id)),
        created_at=datetime(2025, 6, 1, tzinfo=UTC),
        comment_count=5,
    )


def _hit(post_id: str) -> WebSearchHit:
    return WebSearchHit(url=THREAD_URL.format(post_id=post_id), title=f"Thread {post_id}")


def _context(
    plan: ResearchPlan,
    *,
    llm: LLMProvider,
    search: WebSearchProvider,
    source: SourceAdapter | None = None,
    budget: ResearchBudget | None = None,
) -> PipelineContext:
    research = Research(
        original_query="Most underrated US destinations for nature",
        created_at=datetime.now(UTC),
        status=ResearchStatus.DISCOVERING,
        research_config=ResearchConfig(budget=budget or ResearchBudget()),
    )
    context = PipelineContext(
        research=research,
        source=source or _HydratingAdapter(),
        search=search,
        llm=llm,
    )
    context.data["plan"] = plan
    return context


class _CountingSearch:
    """Returns one fresh thread address per call and records the query it got."""

    name = "counting"

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        self.queries.append(query.query)
        return [_hit(f"doc{len(self.queries)}")]


class _SearchWithSecret(_CountingSearch):
    """A provider carrying data outside the protocol, to prove it never leaks."""

    api_key = "super-secret-value"


class _HydratingAdapter:
    """Returns a document for every id it is asked about, and records the batches."""

    name = "hydrating"

    def __init__(self, *, known_ids: Sequence[str] | None = None) -> None:
        self._known_ids = None if known_ids is None else set(known_ids)
        self.batches: list[list[str]] = []

    async def health_check(self) -> bool:
        return True

    async def fetch_documents(self, document_ids: Sequence[str]) -> Sequence[SourceDocument]:
        self.batches.append(list(document_ids))
        return [
            _document(document_id)
            for document_id in document_ids
            if self._known_ids is None or document_id in self._known_ids
        ]

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        raise NotImplementedError


class _FailingAdapter:
    """Hydration is unreachable — the §8.1 outage that must not look like thin evidence."""

    name = "unreachable"

    async def health_check(self) -> bool:
        return True

    async def fetch_documents(self, document_ids: Sequence[str]) -> Sequence[SourceDocument]:
        error = RuntimeError("gateway")
        error.kind = "http_5xx"  # type: ignore[attr-defined]
        raise error

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        raise NotImplementedError


class _SelectiveFailureSearch:
    """Fails for one specific query text, succeeds for everything else."""

    name = "selective_failure"

    def __init__(self, *, failing_query: str) -> None:
        self._failing_query = failing_query
        self.queries: list[str] = []

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        self.queries.append(query.query)
        if self._failing_query in query.query:
            raise TimeoutError("the search provider did not respond")
        return [_hit("gooddoc")]


class _FlakySearch:
    """Fails the first query, then succeeds — a partial outage during discovery."""

    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        self.calls += 1
        if self.calls == 1:
            error = RuntimeError("gateway")
            error.kind = "http_5xx"  # type: ignore[attr-defined]
            raise error
        return [_hit(f"doc{self.calls}")]


class _FixedHitsSearch:
    """Returns the same canned hit list for every query."""

    name = "fixed"

    def __init__(self, hits: Sequence[WebSearchHit]) -> None:
        self._hits = list(hits)

    async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]:
        return self._hits


class _SpyLLM:
    """Records every prompt it is asked to complete, for asserting what it never contains."""

    def __init__(self, responses: Sequence[DiscoveryTurnResponse]) -> None:
        self._responses = deque(responses)
        self.prompts: list[str] = []

    async def complete_structured[T: BaseModel](
        self, *, prompt: str, response_model: type[T]
    ) -> T:
        self.prompts.append(prompt)
        response = self._responses.popleft()
        assert isinstance(response, response_model)
        return response


def _turns(*queries: str) -> list[DiscoveryTurnResponse]:
    return [
        DiscoveryTurnResponse(should_continue=True, next_query=query, reasoning="fresh angle")
        for query in queries
    ]


def _stop() -> DiscoveryTurnResponse:
    return DiscoveryTurnResponse(should_continue=False, reasoning="that's enough coverage")


class TestTheLoopStaysInsideItsBudget:
    async def test_stops_at_max_search_queries_even_if_the_llm_always_continues(self) -> None:
        search = _CountingSearch()
        llm = FakeLLMProvider(
            {
                DiscoveryTurnResponse: _turns(
                    "underrated states nature",
                    "national parks hidden gems",
                    "best road trip destinations",
                )
            }
        )
        context = _context(
            _plan(), llm=llm, search=search, budget=ResearchBudget(max_search_queries=3)
        )

        result = await AgenticDiscoveryStep().run(context)

        assert search.queries == [
            "underrated states nature site:reddit.com",
            "national parks hidden gems site:reddit.com",
            "best road trip destinations site:reddit.com",
        ]
        assert result.data["discovery_queries_issued"] == [
            "underrated states nature",
            "national parks hidden gems",
            "best road trip destinations",
        ]
        assert len(result.data["documents"]) == 3
        assert result.research.status == ResearchStatus.RETRIEVING

    async def test_llm_can_stop_before_the_budget_is_exhausted(self) -> None:
        search = _CountingSearch()
        llm = FakeLLMProvider(
            {DiscoveryTurnResponse: [*_turns("underrated states nature"), _stop()]}
        )
        context = _context(
            _plan(), llm=llm, search=search, budget=ResearchBudget(max_search_queries=10)
        )

        result = await AgenticDiscoveryStep().run(context)

        assert len(search.queries) == 1
        assert len(result.data["documents"]) == 1

    async def test_near_duplicate_query_is_never_sent_to_the_provider(self) -> None:
        search = _CountingSearch()
        llm = FakeLLMProvider(
            {
                DiscoveryTurnResponse: [
                    *_turns(
                        "underrated us national parks",
                        "US underrated national parks",
                        "best hiking trails usa",
                    ),
                    _stop(),
                ]
            }
        )
        context = _context(
            _plan(), llm=llm, search=search, budget=ResearchBudget(max_search_queries=5)
        )

        result = await AgenticDiscoveryStep().run(context)

        assert result.data["discovery_queries_issued"] == [
            "underrated us national parks",
            "best hiking trails usa",
        ]

    async def test_loop_terminates_early_when_the_llm_keeps_repeating_itself(self) -> None:
        search = _CountingSearch()
        same_query = "underrated us national parks"
        llm = FakeLLMProvider({DiscoveryTurnResponse: _turns(*([same_query] * 51))})
        context = _context(
            _plan(), llm=llm, search=search, budget=ResearchBudget(max_search_queries=20)
        )

        # If the loop failed to bound repeated duplicates, this would drain
        # the 51-response queue and raise instead of returning.
        result = await AgenticDiscoveryStep().run(context)

        assert result.data["discovery_queries_issued"] == [same_query]

    async def test_the_loop_stops_once_max_total_posts_is_reached(self) -> None:
        search = _FixedHitsSearch([_hit("doc1"), _hit("doc2"), _hit("doc3")])
        llm = FakeLLMProvider({DiscoveryTurnResponse: _turns("first angle", "second angle")})
        context = _context(
            _plan(),
            llm=llm,
            search=search,
            budget=ResearchBudget(max_search_queries=10, max_total_posts=2),
        )

        result = await AgenticDiscoveryStep().run(context)

        assert result.data["discovery_post_ids_found"] == ["doc1", "doc2"]
        assert result.data["discovery_queries_issued"] == ["first angle"]


class TestAddressesBecomeDocuments:
    async def test_the_query_is_restricted_to_reddit_by_the_tool_not_the_model(self) -> None:
        """A restriction the model can forget is not a restriction (plan §2.11)."""
        search = _CountingSearch()
        llm = FakeLLMProvider({DiscoveryTurnResponse: [*_turns("underrated states"), _stop()]})

        await AgenticDiscoveryStep().run(_context(_plan(), llm=llm, search=search))

        assert search.queries == ["underrated states site:reddit.com"]

    async def test_a_url_that_names_no_post_costs_no_hydrate_call(self) -> None:
        search = _FixedHitsSearch(
            [
                _hit("doc1"),
                WebSearchHit(url="https://www.reddit.com/r/travel/", title="r/travel"),
                WebSearchHit(url="https://example.com/blog/best-states", title="A blog"),
            ]
        )
        adapter = _HydratingAdapter()
        llm = FakeLLMProvider({DiscoveryTurnResponse: [*_turns("underrated states"), _stop()]})

        result = await AgenticDiscoveryStep().run(
            _context(_plan(), llm=llm, search=search, source=adapter)
        )

        assert adapter.batches == [["doc1"]]
        assert [document.id for document in result.data["documents"]] == ["doc1"]

    async def test_the_same_thread_found_twice_is_hydrated_once(self) -> None:
        search = _FixedHitsSearch([_hit("doc1"), _hit("doc1")])
        adapter = _HydratingAdapter()
        llm = FakeLLMProvider({DiscoveryTurnResponse: [*_turns("a", "b different words"), _stop()]})

        await AgenticDiscoveryStep().run(
            _context(_plan(), llm=llm, search=search, source=adapter)
        )

        assert adapter.batches == [["doc1"]]

    async def test_every_collected_id_is_hydrated_in_one_call(self) -> None:
        search = _CountingSearch()
        adapter = _HydratingAdapter()
        llm = FakeLLMProvider(
            {DiscoveryTurnResponse: _turns("first angle", "second angle", "third angle")}
        )
        context = _context(
            _plan(),
            llm=llm,
            search=search,
            source=adapter,
            budget=ResearchBudget(max_search_queries=3),
        )

        await AgenticDiscoveryStep().run(context)

        assert adapter.batches == [["doc1", "doc2", "doc3"]]

    async def test_nothing_found_means_no_hydrate_call_at_all(self) -> None:
        adapter = _HydratingAdapter()
        llm = FakeLLMProvider({DiscoveryTurnResponse: [_stop()]})

        result = await AgenticDiscoveryStep().run(
            _context(_plan(), llm=llm, search=_CountingSearch(), source=adapter)
        )

        assert adapter.batches == []
        assert result.data["documents"] == []
        assert result.data["discovery_documents_unhydrated"] == 0

    async def test_an_id_the_archive_does_not_know_is_recorded_as_unhydrated(self) -> None:
        """Plan §0.1: evidence we located and failed to retrieve is counted,
        not left to be inferred from a shorter list than expected."""
        search = _FixedHitsSearch([_hit("doc1"), _hit("gonedoc")])
        adapter = _HydratingAdapter(known_ids=["doc1"])
        llm = FakeLLMProvider({DiscoveryTurnResponse: [*_turns("underrated states"), _stop()]})

        result = await AgenticDiscoveryStep().run(
            _context(_plan(), llm=llm, search=search, source=adapter)
        )

        assert result.data["discovery_post_ids_found"] == ["doc1", "gonedoc"]
        assert [document.id for document in result.data["documents"]] == ["doc1"]
        assert result.data["discovery_documents_unhydrated"] == 1


class TestNeitherDependencyFailureIsSwallowed:
    async def test_a_failed_search_call_does_not_crash_discovery(self) -> None:
        search = _SelectiveFailureSearch(failing_query="bad query")
        llm = FakeLLMProvider(
            {
                DiscoveryTurnResponse: [
                    *_turns("bad query", "good query different words"),
                    _stop(),
                ]
            }
        )
        context = _context(
            _plan(), llm=llm, search=search, budget=ResearchBudget(max_search_queries=5)
        )

        result = await AgenticDiscoveryStep().run(context)

        assert result.data["discovery_queries_issued"] == [
            "bad query",
            "good query different words",
        ]
        assert [document.id for document in result.data["documents"]] == ["gooddoc"]
        assert result.research.status == ResearchStatus.RETRIEVING

    async def test_a_failed_search_is_counted_against_the_search_provider(self) -> None:
        """§8.1, extended to two dependencies: the snapshot has to say which
        one failed, so a dead search engine is never read as a quiet topic."""
        search = _FlakySearch()
        llm = FakeLLMProvider(
            {DiscoveryTurnResponse: [*_turns("underrated states", "quiet national parks"), _stop()]}
        )
        context = _context(_plan(), llm=llm, search=search)

        await AgenticDiscoveryStep().run(context)

        health = {entry.adapter: entry for entry in get_recorder(context).snapshot()}
        assert (health["flaky"].calls_attempted, health["flaky"].calls_succeeded) == (2, 1)
        assert health["flaky"].failure_kinds == {"http_5xx": 1}

    async def test_a_failed_hydration_is_counted_against_the_source_adapter(self) -> None:
        search = _CountingSearch()
        adapter = _FailingAdapter()
        llm = FakeLLMProvider({DiscoveryTurnResponse: [*_turns("underrated states"), _stop()]})
        context = _context(_plan(), llm=llm, search=search, source=adapter)

        result = await AgenticDiscoveryStep().run(context)

        health = {entry.adapter: entry for entry in get_recorder(context).snapshot()}
        assert health["unreachable"].failure_kinds == {"http_5xx": 1}
        assert health["counting"].calls_succeeded == 1
        assert result.data["documents"] == []
        # The ids were found; retrieving them is what failed. Recording both
        # is what lets §8.1 tell the two apart (plan §0.1).
        assert result.data["discovery_post_ids_found"] == ["doc1"]
        assert result.data["discovery_documents_unhydrated"] == 1

    async def test_a_dead_search_provider_is_an_outage_not_a_quiet_topic(self) -> None:
        """Plan §10 Phase 14.5 acceptance, and the §0.1 obligation behind it:
        every search failing means no evidence, and §8.1 rule 1 has to reach
        ``source_unavailable`` rather than let the run report nothing found."""
        search = _SelectiveFailureSearch(failing_query="")  # every query fails
        adapter = _HydratingAdapter()
        llm = FakeLLMProvider(
            {DiscoveryTurnResponse: _turns("first angle", "second angle different words")}
        )
        context = _context(
            _plan(),
            llm=llm,
            search=search,
            source=adapter,
            budget=ResearchBudget(max_search_queries=2),
        )

        result = await AgenticDiscoveryStep().run(context)

        assert result.data["documents"] == []
        assert adapter.batches == []  # nothing to hydrate, so nothing was spent trying

        assessment = assess_source_health(
            get_recorder(context).snapshot(),
            posts_retrieved=0,
            comments_analyzed=0,
            floors=SourceHealthFloors(),
        )

        assert assessment.outcome is SourceOutcome.UNAVAILABLE
        assert terminal_status(assessment.outcome, budget_limited=False) is (
            ResearchStatus.SOURCE_UNAVAILABLE
        )
        assert "selective_failure" in assessment.reasons[0]

    async def test_both_dependencies_appear_separately_in_the_health_snapshot(self) -> None:
        search = _CountingSearch()
        adapter = _HydratingAdapter()
        llm = FakeLLMProvider({DiscoveryTurnResponse: [*_turns("underrated states"), _stop()]})
        context = _context(_plan(), llm=llm, search=search, source=adapter)

        await AgenticDiscoveryStep().run(context)

        assert [entry.adapter for entry in get_recorder(context).snapshot()] == [
            "counting",
            "hydrating",
        ]


async def test_discovery_prompt_never_contains_provider_internals() -> None:
    search = _SearchWithSecret()
    spy = _SpyLLM([*_turns("underrated states nature"), _stop()])
    context = _context(
        _plan(), llm=spy, search=search, budget=ResearchBudget(max_search_queries=5)
    )

    await AgenticDiscoveryStep().run(context)

    assert spy.prompts  # sanity: the loop actually ran and prompted the LLM
    assert all(search.api_key not in prompt for prompt in spy.prompts)
