"""Agentic Source Discovery's AI contract (plan §4.6 step 3, amended by §2.11).

Each turn the LLM sees the research plan, the queries already searched, what
those queries turned out to be worth, and then proposes the next **batch** of
queries or declares discovery complete. Bounding the number of turns,
rejecting near-duplicate queries, restricting the search to Reddit and
hydrating the results are all deterministic and live in
``pipeline.steps.discovery`` and ``search.tools`` — the same split §4.7 uses
for Document Triage.

**A batch, not a query.** One query per turn made the model call the serial
part of a concurrent pipeline: a measured run issued its searches one round
trip at a time and left roughly two thirds of the analysis window idle,
waiting for documents that had not been found yet. The turn still decides;
it just decides several queries at once.

**What discovery is actually hunting for.** §4.5 draws the respondent pool
only from *polling* threads — open questions whose answer set is not
pre-determined. In a measured run, 74 of 106 threads found were topical and
could not contribute a single counted opinion. The model is told that, and
told how the last turns scored, because a query is worth nothing here unless
it finds a thread where many different people answer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tripfinder.domain.models import ResearchPlan


class DiscoveryTurnResponse(BaseModel):
    """One agent turn: propose the next queries, or stop.

    There is no ``subreddit`` field any more (plan §2.11). Discovery runs
    against a web search engine, which needs no scope to answer, and the
    ``site:`` restriction is applied by the tool rather than written by the
    model — a restriction the model can forget is not a restriction.
    """

    should_continue: bool
    next_queries: list[str] = Field(default_factory=list)
    reasoning: str = Field(min_length=1)


def build_discovery_prompt(
    plan: ResearchPlan,
    *,
    issued_queries: list[str],
    documents_found: int,
    queries_per_turn: int = 1,
    polling_found: int = 0,
    topical_found: int = 0,
) -> str:
    """The prompt sent to the LLM for one discovery turn (plan §6 step 3)."""
    issued = "\n".join(f"- {query}" for query in issued_queries) or "(none yet)"
    scored = (
        f"Of the threads found so far, {polling_found} are open questions that "
        f"count and {topical_found} are not."
        if polling_found or topical_found
        else "No thread has been classified yet."
    )
    return (
        "You are conducting agentic search discovery for a travel-opinion "
        f"research run. Propose up to {queries_per_turn} new search queries, "
        "or stop if you have gathered enough coverage.\n\n"
        f"Topic: {plan.topic}\n"
        f"Criteria: {', '.join(plan.criteria) or '(none)'}\n"
        f"Scope: {plan.scope.type} = {plan.scope.value}\n"
        f"Target entity granularity: {plan.entity_granularity.value}\n"
        f"Relevant subreddits: {', '.join(plan.candidate_subreddits) or '(none)'}\n"
        f"Suggested seed queries: {', '.join(plan.seed_queries) or '(none)'}\n\n"
        f"Queries already searched ({len(issued_queries)}):\n{issued}\n\n"
        f"Reddit threads found so far: {documents_found}. {scored}\n\n"
        "**What counts.** This research counts how many different people "
        "recommend something, so the only threads worth finding are ones "
        f"where many people answer an open question about {plan.scope.value} "
        f"at {plan.entity_granularity.value} level — *\"which one is most "
        "underrated?\"*, *\"what is your favourite and why?\"*. A thread "
        "about one particular place, a trip report, a news article or a "
        "photo post contributes nothing, however relevant it reads: nobody "
        "is answering a question in it. One good open question is worth ten "
        "of those.\n\n"
        f"Propose up to {queries_per_turn} new queries, each meaningfully "
        "different from every query already searched and from each other, "
        "or set should_continue=false. Never propose a query that is "
        "substantially the same as one already searched.\n\n"
        "The query goes to a web search engine, which is already restricted "
        "to Reddit for you - do not write site:, inurl:, quotes, or boolean "
        "operators, and do not name a subreddit unless a person would "
        "naturally type it. Write what someone would type into Google to "
        "find a Reddit thread where people discuss this: a natural phrase, "
        "not keywords. Phrase most of them the way somebody would *ask* the "
        "question, since that is what finds the threads where people answer "
        "it. Vary the angle across the batch - one around a specific "
        "criterion, one around the words enthusiasts would use, one as the "
        "plainest form of the question."
    )
