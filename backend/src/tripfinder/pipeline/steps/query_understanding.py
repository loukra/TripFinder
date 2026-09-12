"""Query Understanding (plan §4.6 step 1, §6): plan · clarification · rejection.

One AI call classifies the raw signals (travel-question or not, scope,
topic, criteria, a confidence per candidate entity granularity). Everything
after that is deterministic: which branch the research takes, and what gets
built for it. This step never touches ``context.source`` — rejecting or
asking for clarification therefore costs nothing (plan §10 Phase 5
acceptance: "a non-travel query is rejected without consuming budget").

A confident plan with no scope (a query naming no specific place) defaults
to ``GLOBAL_SCOPE`` rather than failing — the prompt already asks the model
to do this itself; this is the deterministic backstop for when it doesn't.
"""

from __future__ import annotations

from collections.abc import Sequence

from tripfinder.analysis.query_understanding import (
    CLARIFICATION_QUESTION,
    DEFAULT_REJECTION_REASON,
    GLOBAL_SCOPE,
    OFF_TOPIC_REJECTION_REASON,
    EntityGranularityCandidate,
    QueryUnderstandingResponse,
    build_query_understanding_prompt,
    granularity_label,
)
from tripfinder.domain.config import ResearchBudget
from tripfinder.domain.models import (
    ClarificationOption,
    ClarificationRequest,
    EntityType,
    GranularityConfidence,
    PendingPlan,
    ResearchPlan,
    ResearchStatus,
)
from tripfinder.pipeline.base import PipelineContext


def _clarification_options(
    candidates: Sequence[EntityGranularityCandidate],
) -> list[ClarificationOption]:
    """One option per distinct granularity, most-confident first (plan §6 example)."""
    granularities = dict.fromkeys(candidate.entity_granularity for candidate in candidates)
    return [
        ClarificationOption(label=granularity_label(granularity), entity_granularity=granularity)
        for granularity in granularities
    ]


class QueryUnderstandingStep:
    """Real implementation of plan §4.6 step 1 (stands in for `FakeUnderstandingStep`)."""

    name = "query_understanding"

    async def run(self, context: PipelineContext) -> PipelineContext:
        prompt = build_query_understanding_prompt(context.research.original_query)
        response = await context.llm.complete_structured(
            prompt=prompt, response_model=QueryUnderstandingResponse
        )

        config = context.research.research_config.query_understanding

        # Two different reasons to stop, and they say different things to
        # the user: one is "this cannot be answered by counting opinions",
        # the other is "this product only covers travel".
        if not response.is_recommendation_query:
            context.data["rejection_reason"] = response.rejection_reason or DEFAULT_REJECTION_REASON
            context.research.status = ResearchStatus.REJECTED
            return context

        if config.restrict_to_travel_queries and not response.is_about_travel:
            context.data["rejection_reason"] = OFF_TOPIC_REJECTION_REASON
            context.research.status = ResearchStatus.REJECTED
            return context

        candidates = sorted(
            response.granularity_candidates, key=lambda c: c.confidence, reverse=True
        )
        threshold = config.granularity_threshold

        if not candidates or candidates[0].confidence < threshold:
            clarification = ClarificationRequest(
                question=CLARIFICATION_QUESTION, options=_clarification_options(candidates)
            )
            context.data["clarification_request"] = clarification
            context.research.clarification = clarification
            context.research.pending_plan = PendingPlan(
                normalized_query=response.normalized_query,
                scope=response.scope,
                topic=response.topic,
                criteria=response.criteria,
                seed_queries=response.seed_queries,
                candidate_subreddits=response.candidate_subreddits,
                granularity_candidates=[
                    GranularityConfidence(
                        entity_granularity=candidate.entity_granularity,
                        confidence=candidate.confidence,
                    )
                    for candidate in candidates
                ],
            )
            context.research.status = ResearchStatus.NEEDS_CLARIFICATION
            return context

        top = candidates[0]
        if response.topic is None:
            raise ValueError("Query Understanding returned no topic for a confident plan")

        budget = context.research.research_config.budget
        plan = ResearchPlan(
            normalized_query=response.normalized_query,
            scope=response.scope or GLOBAL_SCOPE,
            entity_granularity=top.entity_granularity,
            granularity_confidence=top.confidence,
            topic=response.topic,
            criteria=response.criteria,
            seed_queries=response.seed_queries[: budget.max_search_queries],
            candidate_subreddits=response.candidate_subreddits,
        )
        context.data["plan"] = plan
        context.research.normalized_query = plan.normalized_query
        context.research.status = ResearchStatus.DISCOVERING
        return context


def build_plan_from_pending(
    pending: PendingPlan, *, entity_granularity: EntityType, budget: ResearchBudget
) -> ResearchPlan:
    """Build the final plan once a clarified research has its granularity (plan §6, Phase 13).

    Reuses exactly what Query Understanding already extracted — no LLM call is
    re-run to answer a question the model already answered, only the tier
    ``/clarify`` was asked to settle.
    """
    candidate = next(
        (
            c
            for c in pending.granularity_candidates
            if c.entity_granularity == entity_granularity
        ),
        None,
    )
    if candidate is None:
        raise ValueError(f"{entity_granularity} was not among the offered candidates")
    if pending.topic is None:
        raise ValueError("Query Understanding returned no topic for this query")
    return ResearchPlan(
        normalized_query=pending.normalized_query,
        scope=pending.scope or GLOBAL_SCOPE,
        entity_granularity=entity_granularity,
        granularity_confidence=candidate.confidence,
        topic=pending.topic,
        criteria=pending.criteria,
        seed_queries=pending.seed_queries[: budget.max_search_queries],
        candidate_subreddits=pending.candidate_subreddits,
    )
