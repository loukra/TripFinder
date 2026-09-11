"""Concurrent strand execution for §4.6 steps 5-7 (plan §2.14, Phase 14.8).

A **strand** is one document carried end to end — fetch, cap, pre-filter,
analyse, accumulate — by one task that waits for no other strand. What the
sequential step list enforced by ordering, this package enforces by two
shared objects instead: :class:`~.budget.RunBudget` (the purse) and
:class:`~.accumulator.Accumulator` (the denominator). Neither makes a strand
wait for another strand's *work*; the only queue in the system is the one in
front of the model, because that is where the money and the provider's rate
limit are.
"""
