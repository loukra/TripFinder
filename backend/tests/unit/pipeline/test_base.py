from datetime import UTC, datetime

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.domain.models import Research, ResearchStatus
from tripfinder.pipeline.base import PipelineContext, ProgressEvent
from tripfinder.search.fake import FakeSearchProvider
from tripfinder.sources.fake.adapter import FakeSourceAdapter


def test_context_starts_with_empty_data_bag_and_progress() -> None:
    research = Research(
        original_query="underrated states",
        created_at=datetime.now(UTC),
        status=ResearchStatus.PENDING,
    )

    context = PipelineContext(
        research=research,
        source=FakeSourceAdapter(),
        search=FakeSearchProvider(),
        llm=FakeLLMProvider(),
    )

    assert context.data == {}
    assert context.progress == []


def test_progress_event_round_trips_through_serialization() -> None:
    event = ProgressEvent(
        sequence=1, step_name="fake_understanding", status=ResearchStatus.DISCOVERING
    )

    restored = ProgressEvent.model_validate_json(event.model_dump_json())

    assert restored == event
