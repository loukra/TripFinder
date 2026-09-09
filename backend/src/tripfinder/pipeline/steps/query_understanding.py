"""Query Understanding (plan §4.6 step 1, §6): plan · clarification · rejection.

One AI call classifies the raw signals (travel-question or not, scope,
topic, criteria, a confidence per candidate entity granularity). Everything
after that is deterministic: which branch the research takes, and what gets
built for it. This step never touches ``context.source`` — rejecting or
asking for clarification therefore costs nothing (plan §10 Phase 5
acceptance: "a non-travel query is rejected without consuming budget").
"""

from __future__ import annotations

from tripfinder.analysis.query_understanding import (
    CLARIFICATION_QUESTION,
    DEFAULT_REJECTION_REASON,
    QueryUnderstandingResponse,
    build_query_understanding_prompt,
    granularity_label,
)
from tripfinder.domain.models import (
    ClarificationOption,
    ClarificationRequest,
    EntityType,
    ResearchPlan,
    ResearchStatus,
)
from tripfinder.pipeline.base import PipelineContext


class QueryUnderstandingStep:
    """Real implementation of plan §4.6 step 1 (stands in for `FakeUnderstandingStep`)."""

    name = "query_understanding"

    async def run(self, context: PipelineContext) -> PipelineContext:
        prompt = build_query_understanding_prompt(context.research.original_query)
        response = await context.llm.complete_structured(
            prompt=prompt, response_model=QueryUnderstandingResponse
        )

        if not response.is_travel_recommendation_query:
            context.data["rejection_reason"] = response.rejection_reason or DEFAULT_REJECTION_REASON
            context.research.status = ResearchStatus.REJECTED
            return context

        candidates = sorted(
            response.granularity_candidates, key=lambda c: c.confidence, reverse=True
        )
        threshold = context.research.research_config.query_understanding.granularity_threshold

        if not candidates or candidates[0].confidence < threshold:
            seen: set[EntityType] = set()
            options: list[ClarificationOption] = []
            for candidate in candidates:
                if candidate.entity_granularity in seen:
                    continue
                seen.add(candidate.entity_granularity)
                options.append(
                    ClarificationOption(
                        label=granularity_label(candidate.entity_granularity),
                        entity_granularity=candidate.entity_granularity,
                    )
                )
            context.data["clarification_request"] = ClarificationRequest(
                question=CLARIFICATION_QUESTION, options=options
            )
            context.research.status = ResearchStatus.NEEDS_CLARIFICATION
            return context

        top = candidates[0]
        if response.scope is None:
            raise ValueError("Query Understanding returned no scope for a confident plan")
        if response.topic is None:
            raise ValueError("Query Understanding returned no topic for a confident plan")

        budget = context.research.research_config.budget
        plan = ResearchPlan(
            normalized_query=response.normalized_query,
            scope=response.scope,
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
