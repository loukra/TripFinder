"""What a run spent at the model, counted rather than claimed (plan §2.15).

Nothing in this codebase counted a token before 14.10. That made the whole
point of reuse unreadable: "answering a question twice costs twice" and "a
cache hit saves money" were assertions about numbers nobody had.

The ledger is deliberately pure and deliberately small. It records what a
provider *reported*, and — separately — how many calls reported nothing at
all. Those must not be added together: a call whose usage is unknown is not
a call that used no tokens, and collapsing the two would make a run against
a provider that reports no usage look free. That is plan §0.1's failure in
its cheapest form, so the unknowns are carried as their own number and
surface in ``statistics`` beside the totals.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CallUsage:
    """What one model call reported using."""

    prompt_tokens: int
    completion_tokens: int


@dataclass
class TokenLedger:
    """One run's model spend, accumulated across every call it makes.

    Mutated from concurrent analysis batches. Every mutation is a read and
    a write of plain ints with no ``await`` between them, so on one event
    loop it is atomic; there is no lock here because there is nothing for
    one to protect.
    """

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls_without_usage: int = 0
    """Calls that returned an answer but no usage figures.

    A fake provider reports none at all, and a real one can omit them. Such
    a call is *unknown*, never zero.
    """

    def record(self, usage: CallUsage | None) -> None:
        """Add one returned call. ``None`` means the provider said nothing."""
        self.calls += 1
        if usage is None:
            self.calls_without_usage += 1
            return
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens

    def totals(self) -> dict[str, int]:
        """The ``statistics`` keys a run carries (plan §2.15).

        ``llm_calls_without_usage`` is always present, including when it is
        zero: a reader comparing two runs has to be able to see that the
        totals cover every call, and a key that only appears when something
        went unreported is a key nobody checks for.
        """
        return {
            "llm_calls": self.calls,
            "llm_prompt_tokens": self.prompt_tokens,
            "llm_completion_tokens": self.completion_tokens,
            "llm_total_tokens": self.prompt_tokens + self.completion_tokens,
            "llm_calls_without_usage": self.calls_without_usage,
        }
