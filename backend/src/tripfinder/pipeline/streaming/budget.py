"""The run's shared purse (plan §2.14.2).

Every strand draws comments and analysis calls from one account, so that a
single 4000-comment thread cannot spend a run's whole budget while sixty-six
other documents go unread — the failure §2.12.3's finding 1 measured
happening in document order.

Three rules, all of them answered immediately so that asking never means
waiting:

* ``max_comments`` and ``max_ai_analysis_items`` are run-wide totals, and
  **both are split by class**. Splitting only the first one was a measured
  mistake: a run with 43 topical and 29 polling documents let evidence
  strands win roughly 770 of 2490 analysis calls first-come-first-served, so
  the corpus that decides the ranking grew by a fifth of what the budget
  bought. §4.5 is explicit that topical material may not buy analysis
  capacity away from it, and the sequential pre-filter enforced exactly that
  by allocating counted comments their budget first;
* **topical material draws from a reserved quota, not from what is left
  over** (plan §4.5). Ordering polling-first cannot survive arrival-order
  processing, and in the measured run it gave topical documents *nothing*:
  ``topical_comments_retrieved`` was 0 because polling consumed the budget
  first. A quota is both compatible with concurrency and closer to what
  §4.5 asks for;
* the dispatch deadline (§2.12.2) gates what may still be *started*, never
  what may finish.

Nothing here locks. One event loop runs all strands, and every method
completes without awaiting, so no two strands can interleave inside one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum


class CommentClass(StrEnum):
    """Which of §4.5's two corpora a comment belongs to."""

    COUNTED = "counted"
    """Polling documents. These decide the ranking."""

    EVIDENCE = "evidence"
    """Topical documents. Illustration and counter-evidence only (§4.5)."""


class RunBudget:
    """One account, shared by every strand.

    ``topical_quota`` is the share of ``max_comments`` reserved for evidence
    material. Counted comments may not draw on it, and evidence comments may
    not draw on anything else, so neither corpus can starve the other.
    """

    def __init__(
        self,
        *,
        max_comments: int,
        max_analysis_items: int,
        max_concurrent_calls: int,
        topical_quota: float = 0.15,
        deadline: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        evidence_allowance = int(max_comments * topical_quota)
        self._allowance = {
            CommentClass.COUNTED: max_comments - evidence_allowance,
            CommentClass.EVIDENCE: evidence_allowance,
        }
        self._spent = {CommentClass.COUNTED: 0, CommentClass.EVIDENCE: 0}
        evidence_items = int(max_analysis_items * topical_quota)
        self._analysis_allowance = {
            CommentClass.COUNTED: max_analysis_items - evidence_items,
            CommentClass.EVIDENCE: evidence_items,
        }
        self._analysis_spent = {CommentClass.COUNTED: 0, CommentClass.EVIDENCE: 0}
        self._deadline = deadline
        self._clock = clock or (lambda: datetime.now(UTC))

        self.call_slots = asyncio.Semaphore(max_concurrent_calls)
        """Concurrency is bounded on model calls, not on strands (§2.14.2)."""

        self.comments_refused = {CommentClass.COUNTED: 0, CommentClass.EVIDENCE: 0}
        self.items_refused_for_budget = 0
        self.items_refused_for_deadline = 0

    def reserve_comments(self, wanted: int, *, comment_class: CommentClass) -> int:
        """How many of ``wanted`` this strand may keep. Answers at once.

        Returns a number that may be zero and is never negative. What was
        refused is tallied, because a corpus that shrank for budget reasons
        has to be distinguishable from one that was genuinely small (§0.1).
        """
        if wanted <= 0:
            return 0
        remaining = self._allowance[comment_class] - self._spent[comment_class]
        granted = max(0, min(wanted, remaining))
        self._spent[comment_class] += granted
        self.comments_refused[comment_class] += wanted - granted
        return granted

    def admit_analysis_batch(self, size: int, *, comment_class: CommentClass) -> bool:
        """Whether one analysis call of ``size`` comments may still be started.

        Each corpus spends its own allowance, so a run that discovers more
        topical threads than polling ones cannot shrink the ranking's
        evidence base (plan §4.5).

        The deadline is checked here rather than around the call, because a
        request is billed the moment it is sent: refusing to *start* saves
        money, abandoning a response in flight saves none (§2.12.2).
        """
        spent = self._analysis_spent[comment_class]
        if spent + size > self._analysis_allowance[comment_class]:
            self.items_refused_for_budget += size
            return False
        if self._deadline is not None and self._clock() > self._deadline:
            self.items_refused_for_deadline += size
            return False
        self._analysis_spent[comment_class] += size
        return True

    @property
    def analysis_items_spent(self) -> int:
        return sum(self._analysis_spent.values())

    def analysis_items_spent_on(self, comment_class: CommentClass) -> int:
        return self._analysis_spent[comment_class]

    def comments_spent(self, comment_class: CommentClass) -> int:
        return self._spent[comment_class]
