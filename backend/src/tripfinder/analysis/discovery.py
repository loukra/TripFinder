"""Agentic Source Discovery's AI contract (plan §4.6 step 3, amended by §2.11).

Each turn the LLM sees the research plan, the queries already searched, and
how many threads have been found, then either proposes the next search query
or declares discovery complete. Bounding the number of turns, rejecting
near-duplicate queries, restricting the search to Reddit and hydrating the
results are all deterministic and live in ``pipeline.steps.discovery`` and
``search.tools`` — the same split §4.7 uses for Document Triage.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tripfinder.domain.models import ResearchPlan


class DiscoveryTurnResponse(BaseModel):
    """One agent turn: propose the next query, or stop.

    There is no ``subreddit`` field any more (plan §2.11). Discovery runs
    against a web search engine, which needs no scope to answer, and the
    ``site:`` restriction is applied by the tool rather than written by the
    model — a restriction the model can forget is not a restriction.
    """

    should_continue: bool
    next_query: str | None = None
    reasoning: str = Field(min_length=1)


def build_discovery_prompt(
    plan: ResearchPlan, *, issued_queries: list[str], documents_found: int
) -> str:
    """The prompt sent to the LLM for one discovery turn (plan §6 step 3)."""
    issued = "\n".join(f"- {query}" for query in issued_queries) or "(none yet)"
    return (
        "You are conducting agentic search discovery for a travel-opinion "
        "research run. Propose the single best next search query, or stop "
        "if you have gathered enough coverage.\n\n"
        f"Topic: {plan.topic}\n"
        f"Criteria: {', '.join(plan.criteria) or '(none)'}\n"
        f"Scope: {plan.scope.type} = {plan.scope.value}\n"
        f"Target entity granularity: {plan.entity_granularity.value}\n"
        f"Relevant subreddits: {', '.join(plan.candidate_subreddits) or '(none)'}\n"
        f"Suggested seed queries: {', '.join(plan.seed_queries) or '(none)'}\n\n"
        f"Queries already searched ({len(issued_queries)}):\n{issued}\n\n"
        f"Reddit threads found so far: {documents_found}\n\n"
        "Propose ONE new search query that is meaningfully different from "
        "every query already searched, or set should_continue=false. Never "
        "propose a query that is substantially the same as one already "
        "searched.\n\n"
        "The query goes to a web search engine, which is already restricted "
        "to Reddit for you - do not write site:, inurl:, quotes, or boolean "
        "operators, and do not name a subreddit unless a person would "
        "naturally type it. Write what someone would type into Google to "
        "find a Reddit thread where people discuss this: a natural phrase, "
        "not keywords. Vary the angle between turns - phrase one query as "
        "the question people would ask, another around a specific criterion, "
        "another around the words enthusiasts would use."
    )
