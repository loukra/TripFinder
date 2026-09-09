"""Agentic Source Discovery's AI contract (plan §4.6 step 3).

Each turn the LLM sees the research plan, the queries already searched, and
how many documents have been found, then either proposes the next search
query or declares discovery complete. Bounding the number of turns,
rejecting near-duplicate queries, and executing the search through the tool
boundary are all deterministic and live in ``pipeline.steps.discovery`` —
the same split §4.7 uses for Document Triage.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tripfinder.domain.models import ResearchPlan


class DiscoveryTurnResponse(BaseModel):
    """One agent turn: propose the next query, or stop."""

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
        f"Candidate subreddits: {', '.join(plan.candidate_subreddits) or '(none)'}\n"
        f"Suggested seed queries: {', '.join(plan.seed_queries) or '(none)'}\n\n"
        f"Queries already searched ({len(issued_queries)}):\n{issued}\n\n"
        f"Documents found so far: {documents_found}\n\n"
        "Propose ONE new search query that is meaningfully different from "
        "every query already searched, or set should_continue=false. Never "
        "propose a query that is substantially the same as one already "
        "searched."
    )
