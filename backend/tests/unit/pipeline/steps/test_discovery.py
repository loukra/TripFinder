from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, HttpUrl

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.analysis.discovery import DiscoveryTurnResponse
from tripfinder.domain.config import ResearchBudget, ResearchConfig
from tripfinder.domain.models import (
    Comment,
    EntityType,
    GeoScope,
    Research,
    ResearchPlan,
    ResearchStatus,
    SourceDocument,
)
from tripfinder.domain.ports import LLMProvider, SourceAdapter, SourceSearchQuery
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.health import get_recorder
from tripfinder.pipeline.steps.discovery import AgenticDiscoveryStep


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
        url=HttpUrl(f"https://reddit.com/r/travel/{document_id}"),
        created_at=datetime(2025, 6, 1, tzinfo=UTC),
        comment_count=5,
    )


def _context(
    plan: ResearchPlan,
    *,
    llm: LLMProvider,
    source: SourceAdapter,
    budget: ResearchBudget | None = None,
) -> PipelineContext:
    research = Research(
        original_query="Most underrated US destinations for nature",
        created_at=datetime.now(UTC),
        status=ResearchStatus.DISCOVERING,
        research_config=ResearchConfig(budget=budget or ResearchBudget()),
    )
    context = PipelineContext(research=research, source=source, llm=llm)
    context.data["plan"] = plan
    return context


class _CountingAdapter:
    """Returns one fresh document per call and records the query it received."""

    name = "counting"

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.search_queries: list[SourceSearchQuery] = []

    async def health_check(self) -> bool:
        return True

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        self.queries.append(query.query)
        self.search_queries.append(query)
        return [_document(f"doc-{len(self.queries)}")]

    async def fetch_document(self, document_id: str) -> SourceDocument:
        raise NotImplementedError

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        raise NotImplementedError


class _AdapterWithSecret(_CountingAdapter):
    """A `SourceAdapter` carrying data outside the protocol, to prove it never leaks."""

    api_key = "super-secret-value"


class _SelectiveFailureAdapter:
    """Fails for one specific query text, succeeds for everything else."""

    name = "selective_failure"

    def __init__(self, *, failing_query: str) -> None:
        self._failing_query = failing_query
        self.queries: list[str] = []

    async def health_check(self) -> bool:
        return True

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        self.queries.append(query.query)
        if query.query == self._failing_query:
            raise TimeoutError("arctic shift did not respond")
        return [_document("good-doc")]

    async def fetch_document(self, document_id: str) -> SourceDocument:
        raise NotImplementedError

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        raise NotImplementedError


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


async def test_stops_at_max_search_queries_even_if_the_llm_always_continues() -> None:
    adapter = _CountingAdapter()
    turns = [
        DiscoveryTurnResponse(
            should_continue=True, next_query=query, subreddit="travel", reasoning="fresh angle"
        )
        for query in [
            "underrated states nature",
            "national parks hidden gems",
            "best road trip destinations",
        ]
    ]
    llm = FakeLLMProvider({DiscoveryTurnResponse: turns})
    context = _context(
        _plan(), llm=llm, source=adapter, budget=ResearchBudget(max_search_queries=3)
    )

    result = await AgenticDiscoveryStep().run(context)

    assert adapter.queries == [
        "underrated states nature",
        "national parks hidden gems",
        "best road trip destinations",
    ]
    assert result.data["discovery_queries_issued"] == adapter.queries
    assert len(result.data["documents"]) == 3
    assert result.research.status == ResearchStatus.RETRIEVING


async def test_llm_can_stop_before_the_budget_is_exhausted() -> None:
    adapter = _CountingAdapter()
    turns = [
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="underrated states nature",
            subreddit="travel",
            reasoning="seed",
        ),
        DiscoveryTurnResponse(should_continue=False, reasoning="that's enough coverage"),
    ]
    llm = FakeLLMProvider({DiscoveryTurnResponse: turns})
    context = _context(
        _plan(), llm=llm, source=adapter, budget=ResearchBudget(max_search_queries=10)
    )

    result = await AgenticDiscoveryStep().run(context)

    assert adapter.queries == ["underrated states nature"]
    assert len(result.data["documents"]) == 1


async def test_near_duplicate_query_is_never_sent_to_the_source() -> None:
    adapter = _CountingAdapter()
    turns = [
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="underrated us national parks",
            subreddit="travel",
            reasoning="seed",
        ),
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="US underrated national parks",
            subreddit="travel",
            reasoning="same idea, reworded",
        ),
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="best hiking trails usa",
            subreddit="travel",
            reasoning="new angle",
        ),
        DiscoveryTurnResponse(should_continue=False, reasoning="enough coverage"),
    ]
    llm = FakeLLMProvider({DiscoveryTurnResponse: turns})
    context = _context(
        _plan(), llm=llm, source=adapter, budget=ResearchBudget(max_search_queries=5)
    )

    result = await AgenticDiscoveryStep().run(context)

    assert adapter.queries == ["underrated us national parks", "best hiking trails usa"]
    assert result.data["discovery_queries_issued"] == adapter.queries


async def test_search_is_scoped_to_the_subreddit_the_llm_named() -> None:
    """Arctic Shift's live search API requires this scope (plan §8) — a
    regression test for the query/subreddit split, not just the fake
    adapter's in-memory contract."""
    adapter = _CountingAdapter()
    turns = [
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="underrated states nature",
            subreddit="travel",
            reasoning="seed",
        ),
        DiscoveryTurnResponse(should_continue=False, reasoning="done"),
    ]
    llm = FakeLLMProvider({DiscoveryTurnResponse: turns})
    context = _context(
        _plan(), llm=llm, source=adapter, budget=ResearchBudget(max_search_queries=5)
    )

    await AgenticDiscoveryStep().run(context)

    assert adapter.search_queries[0].subreddit == "travel"


async def test_a_turn_naming_no_subreddit_is_never_sent_to_the_source() -> None:
    adapter = _CountingAdapter()
    turns = [
        DiscoveryTurnResponse(
            should_continue=True, next_query="underrated states nature", reasoning="forgot scope"
        ),
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="a properly scoped query",
            subreddit="travel",
            reasoning="retry with scope",
        ),
        DiscoveryTurnResponse(should_continue=False, reasoning="done"),
    ]
    llm = FakeLLMProvider({DiscoveryTurnResponse: turns})
    context = _context(
        _plan(), llm=llm, source=adapter, budget=ResearchBudget(max_search_queries=5)
    )

    result = await AgenticDiscoveryStep().run(context)

    assert adapter.queries == ["a properly scoped query"]
    assert result.data["discovery_queries_issued"] == ["a properly scoped query"]


async def test_a_subreddit_outside_the_plans_candidates_is_never_sent_to_the_source() -> None:
    """A hallucinated subreddit is discarded, not trusted (plan §29 — never
    silently invent evidence, applied here to the request itself)."""
    adapter = _CountingAdapter()
    turns = [
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="underrated states nature",
            subreddit="somewhere_not_offered",
            reasoning="hallucinated subreddit",
        ),
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="a properly scoped query",
            subreddit="travel",
            reasoning="retry with an offered subreddit",
        ),
        DiscoveryTurnResponse(should_continue=False, reasoning="done"),
    ]
    llm = FakeLLMProvider({DiscoveryTurnResponse: turns})
    context = _context(
        _plan(), llm=llm, source=adapter, budget=ResearchBudget(max_search_queries=5)
    )

    await AgenticDiscoveryStep().run(context)

    assert adapter.queries == ["a properly scoped query"]


async def test_the_same_query_text_in_two_different_subreddits_is_not_a_duplicate() -> None:
    adapter = _CountingAdapter()
    turns = [
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="underrated states nature",
            subreddit="travel",
            reasoning="seed in r/travel",
        ),
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="underrated states nature",
            subreddit="hiking",
            reasoning="same wording, a different community",
        ),
        DiscoveryTurnResponse(should_continue=False, reasoning="done"),
    ]
    llm = FakeLLMProvider({DiscoveryTurnResponse: turns})
    context = _context(
        ResearchPlan(
            normalized_query="underrated us states for nature",
            scope=GeoScope(type="country", value="United States"),
            entity_granularity=EntityType.STATE,
            granularity_confidence=0.9,
            topic="nature",
            criteria=["underrated"],
            seed_queries=["underrated states nature"],
            candidate_subreddits=["travel", "hiking"],
        ),
        llm=llm,
        source=adapter,
        budget=ResearchBudget(max_search_queries=5),
    )

    await AgenticDiscoveryStep().run(context)

    assert adapter.queries == ["underrated states nature", "underrated states nature"]
    assert [q.subreddit for q in adapter.search_queries] == ["travel", "hiking"]


async def test_loop_terminates_early_when_the_llm_keeps_repeating_the_same_query() -> None:
    adapter = _CountingAdapter()
    same_query = "underrated us national parks"
    turns = [
        DiscoveryTurnResponse(
            should_continue=True, next_query=same_query, subreddit="travel", reasoning="seed"
        )
    ] + [
        DiscoveryTurnResponse(
            should_continue=True,
            next_query=same_query,
            subreddit="travel",
            reasoning="still that one",
        )
        for _ in range(50)
    ]
    llm = FakeLLMProvider({DiscoveryTurnResponse: turns})
    context = _context(
        _plan(), llm=llm, source=adapter, budget=ResearchBudget(max_search_queries=20)
    )

    # If the loop failed to bound repeated duplicates, this would eventually
    # drain the 51-response queue and raise LookupError instead of returning.
    result = await AgenticDiscoveryStep().run(context)

    assert adapter.queries == [same_query]
    assert result.data["discovery_queries_issued"] == [same_query]


async def test_a_failed_search_call_does_not_crash_discovery() -> None:
    adapter = _SelectiveFailureAdapter(failing_query="bad query")
    turns = [
        DiscoveryTurnResponse(
            should_continue=True, next_query="bad query", subreddit="travel", reasoning="try this"
        ),
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="good query different words",
            subreddit="travel",
            reasoning="retry",
        ),
        DiscoveryTurnResponse(should_continue=False, reasoning="done"),
    ]
    llm = FakeLLMProvider({DiscoveryTurnResponse: turns})
    context = _context(
        _plan(), llm=llm, source=adapter, budget=ResearchBudget(max_search_queries=5)
    )

    result = await AgenticDiscoveryStep().run(context)

    assert adapter.queries == ["bad query", "good query different words"]
    assert [document.id for document in result.data["documents"]] == ["good-doc"]
    assert result.research.status == ResearchStatus.RETRIEVING


async def test_discovery_prompt_never_contains_adapter_internals() -> None:
    adapter = _AdapterWithSecret()
    turns = [
        DiscoveryTurnResponse(
            should_continue=True,
            next_query="underrated states nature",
            subreddit="travel",
            reasoning="seed",
        ),
        DiscoveryTurnResponse(should_continue=False, reasoning="done"),
    ]
    spy = _SpyLLM(turns)
    context = _context(
        _plan(), llm=spy, source=adapter, budget=ResearchBudget(max_search_queries=5)
    )

    await AgenticDiscoveryStep().run(context)

    assert spy.prompts  # sanity: the loop actually ran and prompted the LLM
    assert all(adapter.api_key not in prompt for prompt in spy.prompts)


class _FailingSearchAdapter:
    """Fails the first search, then succeeds — a partial outage during discovery."""

    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    async def health_check(self) -> bool:
        return True

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        self.calls += 1
        if self.calls == 1:
            error = RuntimeError("gateway")
            error.kind = "http_5xx"  # type: ignore[attr-defined]
            raise error
        return [_document(f"d{self.calls}")]

    async def fetch_document(self, document_id: str) -> SourceDocument:
        raise LookupError(document_id)

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        return []


async def test_discovery_searches_are_counted_toward_source_health() -> None:
    """A search that fails is a source failure, not an empty result (plan §8.1)."""
    adapter = _FailingSearchAdapter()
    llm = FakeLLMProvider(
        {
            DiscoveryTurnResponse: deque(
                [
                    DiscoveryTurnResponse(
                        should_continue=True,
                        next_query="underrated states",
                        subreddit="travel",
                        reasoning="start",
                    ),
                    DiscoveryTurnResponse(
                        should_continue=True,
                        next_query="quiet national parks",
                        subreddit="travel",
                        reasoning="more",
                    ),
                    DiscoveryTurnResponse(should_continue=False, reasoning="done"),
                ]
            )
        }
    )
    context = _context(_plan(), llm=llm, source=adapter)

    await AgenticDiscoveryStep().run(context)

    (health,) = get_recorder(context).snapshot()
    assert health.adapter == "flaky"
    assert (health.calls_attempted, health.calls_succeeded) == (2, 1)
    assert health.failure_kinds == {"http_5xx": 1}
