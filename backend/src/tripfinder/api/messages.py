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
"""

from __future__ import annotations

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
    ResearchStatus.COMPLETED: (
        "Finished. Every discussion we set out to read was read, so these counts "
        "reflect what people actually said."
    ),
    ResearchStatus.COMPLETED_PARTIAL: (
        "Stopped early on purpose, at a budget or time limit. What we did read was "
        "read properly, so these counts are a real but incomplete sample."
    ),
    ResearchStatus.COMPLETED_DEGRADED: (
        "We could not reach parts of the source during this run. Enough requests "
        "failed that we cannot tell you what proportion recommended anything — "
        "percentages are withheld, and the raw numbers below may be skewed by "
        "which requests happened to succeed."
    ),
    ResearchStatus.SOURCE_UNAVAILABLE: (
        "We could not reach the source at all, so this run gathered no evidence. "
        "There is nothing to show and nothing to conclude. Please try again later."
    ),
    ResearchStatus.FAILED: "Something went wrong inside this research. Nothing was produced.",
    ResearchStatus.CANCELLED: "You cancelled this research before it finished.",
}


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
}
"""Plan §0.1 rule 3 applied to a broken run: every failure names its own cause.

``ResearchStatus.FAILED``'s generic wording says only that nothing was
produced. These say *why* nothing was produced, and each one is written so
it cannot be mistaken for the ``completed`` message above — a run that
failed found nothing because it could not look, which is the one thing a
thin-but-honest result never means.
"""


def status_message(status: ResearchStatus) -> str:
    """The §7.1 wording for a status."""
    return STATUS_MESSAGES[status]


def percentages_suppressed(status: ResearchStatus) -> bool:
    """§8.1 rule 2: a degraded run's denominator is not a sample, so no shares."""
    return status is ResearchStatus.COMPLETED_DEGRADED


def research_message(status: ResearchStatus, failure: ResearchFailure | None = None) -> str:
    """The wording for one run: its named cause when it failed, its status otherwise."""
    if status is ResearchStatus.FAILED and failure is not None:
        return FAILURE_MESSAGES[failure.kind]
    return status_message(status)
