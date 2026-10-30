"""The §7.1 status table, as user-facing wording.

Plan §0.1 rule 4: *a degraded outcome may not be described in the same
words as a genuine one*. That is a property of the copy itself, not of the
code that picks it, so the copy lives in one table where it can be read
side by side and tested for overlap.

Each message answers one question — *what does this run promise about what
it found?* — and every entry answers it differently:

* ``completed`` promises a real look at the source;
* ``completed_partial`` promises a real but deliberately shortened look;
* ``completed_degraded`` promises nothing about proportions, because the
  sample is not one;
* ``source_unavailable`` promises nothing at all.

Plan §2.13 adds one more thing a run can be — **provisional** — and it needs
its own wording for the same reason. A run still analysing has real counts
from real comments and no denominator yet; a run the user cancelled has
counts that stopped where they stopped. Neither is a finding about the
world, and neither may be described in the words a finished run uses.
"""

from __future__ import annotations

import random

from tripfinder.domain.models import FailureKind, ResearchFailure, ResearchStatus

STATUS_MESSAGES: dict[ResearchStatus, str] = {
    ResearchStatus.PENDING: "Queued. This research has not started yet.",
    ResearchStatus.UNDERSTANDING: "Working out what you are asking for.",
    ResearchStatus.NEEDS_CLARIFICATION: "One question before we start searching.",
    ResearchStatus.REJECTED: "This is not a travel recommendation question, so nothing was run.",
    ResearchStatus.DISCOVERING: "Searching for discussions that answer your question.",
    ResearchStatus.RETRIEVING: "Reading the discussions we found.",
    ResearchStatus.ANALYZING: "Working out what each comment recommends.",
    ResearchStatus.AGGREGATING: "Counting who recommended what.",
    ResearchStatus.COMPLETED: "Finished. Every discussion found was read.",
    ResearchStatus.COMPLETED_PARTIAL: (
        "Stopped at the time limit. Everything read up to then is counted."
    ),
    ResearchStatus.COMPLETED_DEGRADED: (
        "We could not reach parts of the source, so percentages are withheld. "
        "The counts may lean towards whatever requests got through."
    ),
    ResearchStatus.SOURCE_UNAVAILABLE: (
        "We could not reach the source at all, so this run gathered no evidence. "
        "There is nothing to show and nothing to conclude. Please try again later."
    ),
    ResearchStatus.FAILED: "Something went wrong inside this research. Nothing was produced.",
    ResearchStatus.CANCELLED: "You cancelled this research before it finished.",
}


PROGRESS_FLAVOR: dict[ResearchStatus, list[str]] = {
    ResearchStatus.PENDING: [
        "Queued. This research has not started yet.",
        "In line. A worker will pick this up any second now.",
        "Waiting for a free worker — shouldn't be long.",
    ],
    ResearchStatus.UNDERSTANDING: [
        "Working out what you are asking for.",
        "Reading your question carefully before doing anything else.",
        "Making sense of your question.",
    ],
    ResearchStatus.DISCOVERING: [
        "Searching for discussions that answer your question.",
        "Digging through Reddit threads for opinions worth counting.",
        "Casting a wide net across the relevant subreddits.",
        "Hunting down every thread that might have an answer.",
    ],
    ResearchStatus.RETRIEVING: [
        "Reading the discussions we found.",
        "Pulling up every comment thread worth a closer look.",
        "Opening each thread and scrolling all the way down.",
    ],
    ResearchStatus.ANALYZING: [
        "Working out what each comment recommends.",
        "Reading between the lines, one comment at a time.",
        "Figuring out who's recommending what, and how strongly.",
    ],
    ResearchStatus.AGGREGATING: [
        "Counting who recommended what.",
        "Tallying the votes.",
        "Adding it all up.",
    ],
}
"""A playful variant per in-progress stage, picked at random on each request.

Deliberately does not cover the ``§7.1`` terminal outcomes, ``rejected``,
``needs_clarification`` or ``cancelled`` — plan §0.1 rule 4 requires those to
be exact and stable, never one of several interchangeable phrasings. This is
copy for "what is happening right now" only, where no promise is being made
about what the run will find."""


FAILURE_MESSAGES: dict[FailureKind, str] = {
    FailureKind.LLM_CREDENTIAL: (
        "This research could not reach the language model it depends on: the credential "
        "is missing or was rejected. Nothing was retrieved and nothing was analysed, so "
        "there is nothing to show — a configuration fault on our side, not a quiet topic."
    ),
    FailureKind.LLM_UNAVAILABLE: (
        "The language model this research depends on could not be reached. Nothing was "
        "analysed, so there is nothing to show and nothing to conclude. Please try again "
        "later."
    ),
    FailureKind.LLM_REQUEST_REJECTED: (
        "The language model rejected a request this research made. That is a defect on "
        "our side rather than a shortage of opinions; nothing was analysed and nothing "
        "is shown."
    ),
    FailureKind.LLM_INVALID_RESPONSE: (
        "The language model's answer could not be trusted — it was refused, cut short, or "
        "did not match the shape this research requires. Rather than guess at the missing "
        "parts, the run was stopped, so there is nothing to show."
    ),
    FailureKind.UNEXPECTED_ERROR: (
        "This research hit an unexpected internal error and was stopped before finishing. "
        "That is a defect in the system running it, not a shortage of opinions — nothing "
        "here reflects what the source does or doesn't say."
    ),
}
"""Plan §0.1 rule 3 applied to a broken run: every failure names its own cause.

``ResearchStatus.FAILED``'s generic wording says only that nothing was
produced. These say *why* nothing was produced, and each one is written so
it cannot be mistaken for the ``completed`` message above — a run that
failed found nothing because it could not look, which is the one thing a
thin-but-honest result never means.
"""


PROVISIONAL_STATUSES = frozenset({ResearchStatus.ANALYZING, ResearchStatus.CANCELLED})
"""The statuses whose results object, if there is one, is unfinished (plan §2.13).

``analyzing`` is the ordinary case: the run is still reading, and the
corpus is still open. ``cancelled`` is the same corpus frozen where the user
stopped it — §2.13.3 lets such a run show the evidence it already had rather
than throw it away, and it is unfinished in exactly the same way.
"""


PROVISIONAL_MESSAGES: dict[ResearchStatus, str] = {
    ResearchStatus.ANALYZING: (
        "Still reading. Every count below comes from a comment we have already "
        "analysed, so none of them is invented — but the reading is not finished, "
        "the counts can still grow, and no percentage can be worked out until they "
        "stop."
    ),
    ResearchStatus.CANCELLED: (
        "You stopped this research while it was still reading. What is below is what "
        "had been counted by then: real, incomplete, and now final only because it was "
        "interrupted. No percentage can be worked out from a count that never finished."
    ),
}
"""What a provisional results page says about itself (plan §2.13.1, §0.1 rule 4).

Both entries say the same load-bearing thing in their own words — *these
counts are real and they are not finished* — and neither may be confused
with ``completed`` ("every discussion we set out to read was read") or with
``completed_partial`` ("we stopped early on purpose"), which describe runs
that closed their corpus and computed a denominator from it.
"""


def status_message(status: ResearchStatus) -> str:
    """The §7.1 wording for a status."""
    return STATUS_MESSAGES[status]


def is_provisional(status: ResearchStatus) -> bool:
    """Whether a results object at this status is still unfinished (plan §2.13)."""
    return status in PROVISIONAL_STATUSES


def percentages_suppressed(status: ResearchStatus) -> bool:
    """No shares where the denominator is not a closed sample.

    Two cases, one rule. §8.1 rule 2: a degraded run's denominator is not a
    sample of anything, because which requests succeeded decided who is in
    it. Plan §2.13.1: a provisional run's denominator is not closed yet, so
    §4.4's label — *"X% of people who answered mentioned this"* — has no
    truth value, since "people who answered" is still growing.
    """
    return status is ResearchStatus.COMPLETED_DEGRADED or is_provisional(status)


def results_message(status: ResearchStatus) -> str:
    """The wording for a *results page* at this status (plan §2.13).

    Separate from :func:`research_message` because the two answer different
    questions. While a run is analysing, the status endpoint is asked *what
    is happening* — "reading between the lines, one comment at a time" — and
    the results endpoint is asked *what do these numbers mean*, which
    ``PROGRESS_FLAVOR`` has no answer to.
    """
    provisional = PROVISIONAL_MESSAGES.get(status)
    return provisional if provisional is not None else status_message(status)


def research_message(status: ResearchStatus, failure: ResearchFailure | None = None) -> str:
    """The wording for one run: its named cause when it failed, a randomly
    picked variant while it is still in progress, or its plain status
    wording otherwise."""
    if status is ResearchStatus.FAILED and failure is not None:
        return FAILURE_MESSAGES[failure.kind]
    variants = PROGRESS_FLAVOR.get(status)
    if variants:
        return random.choice(variants)
    return status_message(status)
