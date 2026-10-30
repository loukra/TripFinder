import pytest
from pydantic import BaseModel

from tripfinder.ai.fake import FakeLLMProvider
from tripfinder.domain.usage import TokenLedger


class _Widget(BaseModel):
    count: int


class _Gadget(BaseModel):
    label: str


async def test_returns_registered_response_for_its_model_type() -> None:
    provider = FakeLLMProvider({_Widget: _Widget(count=3)})

    result = await provider.complete_structured(prompt="anything", response_model=_Widget)

    assert result == _Widget(count=3)


async def test_raises_for_unregistered_response_model() -> None:
    provider = FakeLLMProvider({_Widget: _Widget(count=3)})

    with pytest.raises(LookupError):
        await provider.complete_structured(prompt="anything", response_model=_Gadget)


async def test_raises_when_registered_response_type_does_not_match() -> None:
    provider = FakeLLMProvider({_Widget: _Gadget(label="oops")})

    with pytest.raises(TypeError):
        await provider.complete_structured(prompt="anything", response_model=_Widget)


async def test_ignores_prompt_content_deterministic_regardless_of_input() -> None:
    provider = FakeLLMProvider({_Widget: _Widget(count=7)})

    first = await provider.complete_structured(prompt="a", response_model=_Widget)
    second = await provider.complete_structured(
        prompt="completely different", response_model=_Widget
    )

    assert first == second == _Widget(count=7)


async def test_queued_responses_are_drained_one_per_call_in_order() -> None:
    provider = FakeLLMProvider({_Widget: [_Widget(count=1), _Widget(count=2)]})

    first = await provider.complete_structured(prompt="a", response_model=_Widget)
    second = await provider.complete_structured(prompt="b", response_model=_Widget)

    assert (first, second) == (_Widget(count=1), _Widget(count=2))


async def test_exhausted_queue_raises_rather_than_repeating() -> None:
    provider = FakeLLMProvider({_Widget: [_Widget(count=1)]})
    await provider.complete_structured(prompt="a", response_model=_Widget)

    with pytest.raises(LookupError):
        await provider.complete_structured(prompt="b", response_model=_Widget)


async def test_queued_response_of_the_wrong_type_raises() -> None:
    provider = FakeLLMProvider({_Widget: [_Gadget(label="oops")]})

    with pytest.raises(TypeError):
        await provider.complete_structured(prompt="a", response_model=_Widget)


# Plan §2.15: the fake counts its calls too, so the code that reads a run's
# spend is exercised by the ordinary suite rather than only in production.


async def test_the_fake_counts_its_calls_and_costs_none_of_them() -> None:
    ledger = TokenLedger()
    provider = FakeLLMProvider({_Gadget: _Gadget(label="ok")}, ledger=ledger)

    await provider.complete_structured(prompt="a", response_model=_Gadget)
    await provider.complete_structured(prompt="b", response_model=_Gadget)

    assert ledger.totals() == {
        "llm_calls": 2,
        "llm_prompt_tokens": 0,
        "llm_completion_tokens": 0,
        "llm_total_tokens": 0,
        "llm_calls_without_usage": 2,
    }


async def test_a_canned_answer_is_unknown_rather_than_free() -> None:
    """Zero tokens over zero calls and zero tokens over two calls say different things."""
    ledger = TokenLedger()
    provider = FakeLLMProvider({_Gadget: _Gadget(label="ok")}, ledger=ledger)

    await provider.complete_structured(prompt="a", response_model=_Gadget)

    assert ledger.totals() != TokenLedger().totals()
