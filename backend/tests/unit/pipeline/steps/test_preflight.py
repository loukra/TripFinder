"""Source preflight (plan §8.1): no reachable adapter means no research, at zero cost."""

from __future__ import annotations

from collections.abc import Sequence

from builders.phase7 import make_context, make_document
from tripfinder.domain.models import (
    Comment,
    ResearchStatus,
    SourceDocument,
    SourceOutcome,
)
from tripfinder.domain.ports import SourceSearchQuery
from tripfinder.pipeline.steps.preflight import UNREACHABLE, SourcePreflightStep


class ProbeAdapter:
    """Records every call so a test can prove preflight spent nothing else."""

    name = "probe"

    def __init__(self, *, healthy: bool | Exception) -> None:
        self._healthy = healthy
        self.calls: list[str] = []

    async def health_check(self) -> bool:
        self.calls.append("health_check")
        if isinstance(self._healthy, Exception):
            raise self._healthy
        return self._healthy

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceDocument]:
        self.calls.append("search")
        return [make_document("d1")]

    async def fetch_document(self, document_id: str) -> SourceDocument:
        self.calls.append("fetch_document")
        raise LookupError(document_id)

    async def fetch_comments(self, document: SourceDocument) -> Sequence[Comment]:
        self.calls.append("fetch_comments")
        return []


async def test_a_reachable_source_passes_without_changing_the_research() -> None:
    adapter = ProbeAdapter(healthy=True)
    context = make_context(source=adapter, status=ResearchStatus.PENDING)

    await SourcePreflightStep().run(context)

    assert context.research.status is ResearchStatus.PENDING
    assert context.research.diagnostics.source_outcome is None
    assert adapter.calls == ["health_check"]


async def test_an_unreachable_source_terminates_the_research_immediately() -> None:
    adapter = ProbeAdapter(healthy=False)
    context = make_context(source=adapter, status=ResearchStatus.PENDING)

    await SourcePreflightStep().run(context)

    assert context.research.status is ResearchStatus.SOURCE_UNAVAILABLE
    assert context.research.diagnostics.source_outcome is SourceOutcome.UNAVAILABLE
    assert context.research.results == []


async def test_the_failing_adapter_and_its_failure_kind_are_named() -> None:
    """§8.1 rule 1 requires a machine-readable error naming the adapters."""
    context = make_context(source=ProbeAdapter(healthy=False))

    await SourcePreflightStep().run(context)

    (health,) = context.research.diagnostics.source_health
    assert health.adapter == "probe"
    assert health.failure_kinds == {UNREACHABLE: 1}
    assert health.success_rate == 0.0


async def test_a_health_check_that_raises_counts_as_unreachable() -> None:
    context = make_context(source=ProbeAdapter(healthy=ConnectionError("no route")))

    await SourcePreflightStep().run(context)

    assert context.research.status is ResearchStatus.SOURCE_UNAVAILABLE


async def test_preflight_spends_nothing_beyond_the_probe() -> None:
    """Discovering the outage after paying for query understanding is the waste (§8.1)."""
    adapter = ProbeAdapter(healthy=False)
    context = make_context(source=adapter)

    await SourcePreflightStep().run(context)

    assert adapter.calls == ["health_check"]


async def test_a_passing_probe_does_not_flatter_the_call_accounting() -> None:
    """Preflight is a gate, not a sample of how well the source served the run."""
    context = make_context(source=ProbeAdapter(healthy=True))

    await SourcePreflightStep().run(context)

    assert context.research.diagnostics.source_health == []
