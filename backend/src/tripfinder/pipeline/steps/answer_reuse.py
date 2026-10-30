"""Answering a question that has already been answered (plan §2.15, §4.6 step 1.5).

This step does two jobs, and they are the same job seen from both ends.

**It stamps the run with its key.** Query Understanding has just decided
what the question means; ``plan_fingerprint`` turns that into a lookup key,
and the run stores both, so that this run can answer a later one.

**It looks the key up.** If an earlier run holds the same key and is recent
enough, this run shows that run's answer instead of paying for its own — no
discovery call, no retrieval, no analysis.

Four rules decide whether a stored run may answer, and each one exists
because the alternative would put a wrong or misleading number in front of
somebody:

1. **The run read its corpus properly.** ``completed`` and
   ``completed_partial`` qualify; ``completed_degraded``, ``failed``,
   ``cancelled`` and ``source_unavailable`` never do.

   §2.15's acceptance originally said ``completed`` alone, and that was
   amended after it was measured (§2.15.2): since the streaming pipeline
   landed, **no real run has ever reached** ``completed`` — every one stops
   at the duration budget as ``completed_partial`` with
   ``budget_limit_reached``. The rule as written made reuse a feature that
   could not fire.

   The distinction that matters is not "finished" but "was this a real
   reading?", and §2.12.2 already answers it for a budget-limited run:
   *what was read was read properly, and the corpus is a real but
   incomplete sample*. A degraded run is the opposite — §8.1 suppressed its
   percentages because the source was unhealthy — and a failed, cancelled
   or unreachable one never had a corpus at all.

2. **Inside the window.** ``ReuseConfig.window_days``, measured from the
   stored run's ``created_at``.
3. **Never a reuse of a reuse.** A run that was itself answered from the
   archive is not a source. Otherwise the date on the label would drift
   forward one hop at a time until a year-old answer was being presented as
   this month's, which is exactly the error rule 1 of §2.15 forbids.
4. **Only if this run is allowed to.** ``ReuseConfig.enabled`` is off for a
   run created with ``fresh=true``, and then this step looks nothing up.

On a hit the answer is copied whole — results, weak results, statistics,
diagnostics **and the status** — because those describe *the answer*, not
the copying. The status especially: a partial answer reused under
``completed`` would be §0.1 rule 4 committed by a step whose whole job is to
stop old answers from looking new. So a reused partial is itself
``completed_partial``, says §7.1's partial sentence, and carries the same
flags. Nothing is laundered by being copied.

The statistics say the answer came from 38 discussions because it did; what
this run spent is written over the top of them by the runner, from the token
ledger, so a hit and a miss can be compared as two numbers rather than two
claims (plan §2.15).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from tripfinder.domain.models import (
    REUSABLE_STATUSES,
    Research,
    ResearchPlan,
    ReusedAnswer,
)
from tripfinder.domain.reuse import plan_fingerprint
from tripfinder.pipeline.base import PipelineContext

logger = logging.getLogger(__name__)


class AnswerReuseStep:
    """Plan §4.6 step 1.5 — remember this run's key, and answer from an old run if one fits."""

    name = "answer_reuse"

    async def run(self, context: PipelineContext) -> PipelineContext:
        plan = context.data.get("plan")
        if not isinstance(plan, ResearchPlan):
            # Query Understanding rejected the question or asked for
            # clarification. There is nothing to key on, and the run is
            # already halting.
            return context

        research = context.research
        fingerprint = plan_fingerprint(plan)
        research.plan = plan
        research.plan_fingerprint = fingerprint

        config = context.research.research_config.reuse
        if not config.enabled or context.archive is None:
            return context

        not_before = research.created_at - timedelta(days=config.window_days)
        prior = await context.archive.find_by_fingerprint(
            fingerprint=fingerprint, not_before=not_before
        )
        if prior is None or not _may_answer(prior, for_research=research):
            return context

        _copy_answer(prior, onto=research)
        context.answered = True
        logger.info(
            "reuse: research %s answered from %s, produced %s",
            research.id,
            prior.id,
            prior.created_at.isoformat(),
        )
        return context


def _may_answer(prior: Research, *, for_research: Research) -> bool:
    """Whether a stored run is allowed to answer for this one (rules 1 and 3 above)."""
    if prior.id == for_research.id:
        return False
    if prior.status not in REUSABLE_STATUSES:
        return False
    return prior.reused is None


def _copy_answer(prior: Research, *, onto: Research) -> None:
    """Take the earlier run's answer whole, and say whose it is.

    ``normalized_query`` comes across too: two differently worded questions
    with the same plan share a normalization, and the run that is shown
    should read as the answer it is showing.
    """
    onto.results = list(prior.results)
    onto.weak_results = list(prior.weak_results)
    onto.statistics = dict(prior.statistics)
    onto.diagnostics = prior.diagnostics.model_copy(deep=True)
    onto.normalized_query = prior.normalized_query
    onto.reused = ReusedAnswer(research_id=prior.id, answered_at=prior.created_at)
    # The source's status, never ``completed``. A partial answer relabelled
    # as a finished one would describe a degraded outcome in the words of a
    # genuine one — §0.1 rule 4 — and it would be this step that did it.
    onto.status = prior.status
