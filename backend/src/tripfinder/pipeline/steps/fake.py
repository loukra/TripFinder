"""Fake step implementations exercising the pipeline machinery end-to-end.

These are Phase 2's placeholder logic — deterministic and canned, not the
real business rules from plan §4.6 (query understanding, discovery, comment
analysis, aggregation). Later phases replace each step's body one at a time;
the protocol and runner around them do not change.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from tripfinder.domain.models import Comment, ResearchStatus, Result, SourceDocument
from tripfinder.domain.ports import WebSearchQuery
from tripfinder.pipeline.base import PipelineContext
from tripfinder.search.reddit_urls import post_id_from_url


class FakeUnderstandingStep:
    """Stands in for Query Understanding (plan §4.6 step 1, real logic in Phase 5)."""

    name = "fake_understanding"

    async def run(self, context: PipelineContext) -> PipelineContext:
        context.research.normalized_query = context.research.original_query.strip().lower()
        context.research.status = ResearchStatus.DISCOVERING
        return context


class FakeDiscoveryStep:
    """Stands in for Agentic Source Discovery (plan §4.6 step 3, real logic in Phase 6)."""

    name = "fake_discovery"

    async def run(self, context: PipelineContext) -> PipelineContext:
        search_text = context.research.normalized_query or context.research.original_query
        hits = await context.search.search(WebSearchQuery(query=search_text))
        post_ids = [
            post_id for hit in hits if (post_id := post_id_from_url(hit.url)) is not None
        ]
        documents = await context.source.fetch_documents(list(dict.fromkeys(post_ids)))
        context.data["documents"] = list(documents)
        context.research.status = ResearchStatus.RETRIEVING
        return context


class FakeRetrievalStep:
    """Stands in for Content Retrieval (plan §4.6 step 5, real logic in Phase 7)."""

    name = "fake_retrieval"

    async def run(self, context: PipelineContext) -> PipelineContext:
        documents: list[SourceDocument] = context.data.get("documents", [])
        comments: list[Comment] = []
        for document in documents:
            comments.extend(await context.source.fetch_comments(document))
        context.data["comments"] = comments
        context.research.status = ResearchStatus.ANALYZING
        return context


class FakeMention(BaseModel):
    """One fake extracted mention — a stand-in for the real §5 ``EntityMention``."""

    entity_name: str
    user_id: str


class FakeAnalysisResponse(BaseModel):
    """The canned structured response ``FakeAnalysisStep`` requests from the LLM."""

    mentions: list[FakeMention]


class FakeAnalysisStep:
    """Stands in for Comment Analysis (plan §4.6 step 7, real logic in Phase 8).

    Exercises the ``LLMProvider`` port with a structured-output call, same as
    the real step will, but the response is a canned fixture rather than a
    model's extraction.
    """

    name = "fake_analysis"

    async def run(self, context: PipelineContext) -> PipelineContext:
        comments: list[Comment] = context.data.get("comments", [])
        prompt = "\n".join(comment.body for comment in comments)
        analysis = await context.llm.complete_structured(
            prompt=prompt, response_model=FakeAnalysisResponse
        )
        context.data["mentions"] = analysis.mentions
        context.research.status = ResearchStatus.AGGREGATING
        return context


class FakeAggregationStep:
    """Stands in for Aggregation + Ranking (plan §4.6 steps 11/12, real math in Phase 11).

    Counts distinct supporting users per entity and sorts by supporter count
    descending — the shape of the real §4 metric, not its exact formulas.
    """

    name = "fake_aggregation"

    async def run(self, context: PipelineContext) -> PipelineContext:
        mentions: list[FakeMention] = context.data.get("mentions", [])
        comments: list[Comment] = context.data.get("comments", [])
        documents: list[SourceDocument] = context.data.get("documents", [])

        supporters: dict[str, set[str]] = defaultdict(set)
        for mention in mentions:
            supporters[mention.entity_name].add(mention.user_id)

        pool_size = len({mention.user_id for mention in mentions})
        discussion_count = len({comment.source_document_id for comment in comments})

        results = [
            Result(
                entity_id=entity_name.lower().replace(" ", "_"),
                entity_name=entity_name,
                supporter_count=len(users),
                share=len(users) / pool_size if pool_size else 0.0,
                respondent_pool_size=pool_size,
                discussion_count=discussion_count,
                weighted_score=float(len(users)),
                confidence=1.0,
            )
            for entity_name, users in supporters.items()
        ]
        results.sort(key=lambda result: (-result.supporter_count, result.entity_id))

        context.research.results = results
        context.research.statistics["documents_retrieved"] = len(documents)
        context.research.statistics["comments_retrieved"] = len(comments)
        context.research.status = ResearchStatus.COMPLETED
        return context
