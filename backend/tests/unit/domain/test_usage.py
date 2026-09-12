"""The token ledger (plan §2.15): what a run spent, and what it does not know.

One rule does all the work here, and it is plan §0.1 in its cheapest form:
a call whose cost was never reported is *unknown*, not zero. Collapsing the
two would make a run against a provider that reports no usage look free,
which is the most flattering possible lie about a bill.
"""

from __future__ import annotations

from tripfinder.domain.usage import CallUsage, TokenLedger


def test_a_fresh_ledger_has_spent_nothing() -> None:
    assert TokenLedger().totals() == {
        "llm_calls": 0,
        "llm_prompt_tokens": 0,
        "llm_completion_tokens": 0,
        "llm_total_tokens": 0,
        "llm_calls_without_usage": 0,
    }


def test_calls_accumulate() -> None:
    ledger = TokenLedger()

    ledger.record(CallUsage(prompt_tokens=1200, completion_tokens=340))
    ledger.record(CallUsage(prompt_tokens=800, completion_tokens=160))

    assert ledger.totals() == {
        "llm_calls": 2,
        "llm_prompt_tokens": 2000,
        "llm_completion_tokens": 500,
        "llm_total_tokens": 2500,
        "llm_calls_without_usage": 0,
    }


def test_an_unreported_call_is_counted_but_not_costed() -> None:
    ledger = TokenLedger()

    ledger.record(None)

    totals = ledger.totals()
    assert totals["llm_calls"] == 1
    assert totals["llm_calls_without_usage"] == 1
    assert totals["llm_total_tokens"] == 0


def test_an_unreported_call_is_distinguishable_from_a_free_one() -> None:
    """The §0.1 distinction, at the level of a number.

    Two runs both report zero tokens. One made no calls; the other made
    three that nobody measured. A reader has to be able to tell them apart,
    and ``llm_calls_without_usage`` is the only thing that says so.
    """
    nothing_spent = TokenLedger()
    nothing_measured = TokenLedger()
    for _ in range(3):
        nothing_measured.record(None)

    assert nothing_spent.totals()["llm_total_tokens"] == 0
    assert nothing_measured.totals()["llm_total_tokens"] == 0
    assert nothing_spent.totals() != nothing_measured.totals()


def test_a_measured_run_and_an_unmeasured_one_do_not_average_out() -> None:
    """A known call plus an unknown one is not two known calls."""
    ledger = TokenLedger()

    ledger.record(CallUsage(prompt_tokens=500, completion_tokens=100))
    ledger.record(None)

    totals = ledger.totals()
    assert totals["llm_calls"] == 2
    assert totals["llm_calls_without_usage"] == 1
    assert totals["llm_total_tokens"] == 600
