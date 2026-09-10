"""Content Retrieval (plan §4.6 step 5).

Fetches comment trees for the documents triage kept — and only those. An
excluded document costs nothing here, which is why triage runs first.

Polling documents are retrieved before topical ones (plan §4.5 "budget
priority"): topical threads cannot change the ranking, so they may only
spend budget the polling corpus left behind.

Three things are bounded or recorded rather than assumed:

* ``maxComments`` caps the corpus, and everything it cost is recorded;
* a comment id seen twice is counted once (a comment can surface under more
  than one document after a crosspost);
* every fetch is tallied into the run's ``SourceHealthRecorder``, so a
  partial outage shows up in §8.1's accounting instead of silently shrinking
  the evidence.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from tripfinder.domain.models import (
    Comment,
    ResearchFlag,
    ResearchStatus,
    SourceDocument,
    SuppressionReason,
)
from tripfinder.pipeline.base import PipelineContext
from tripfinder.pipeline.health import SourceHealthRecorder, get_recorder
from tripfinder.sources.failures import failure_kind

logger = logging.getLogger(__name__)


class ContentRetrievalStep:
    """Real implementation of plan §4.6 step 5."""

    name = "content_retrieval"

    async def run(self, context: PipelineContext) -> PipelineContext:
        polling_documents: list[SourceDocument] = context.data.get("polling_documents", [])
        topical_documents: list[SourceDocument] = context.data.get("topical_documents", [])
        max_comments = context.research.research_config.budget.max_comments
        diagnostics = context.research.diagnostics
        recorder = get_recorder(context)

        seen_comment_ids: set[str] = set()
        polling_comments: list[Comment] = []
        topical_comments: list[Comment] = []
        documents_retrieved = 0
        comments_dropped_for_budget = 0
        documents_unvisited = 0

        # Polling first, always: topical threads spend only leftover budget.
        for documents, sink in (
            (polling_documents, polling_comments),
            (topical_documents, topical_comments),
        ):
            for index, document in enumerate(documents):
                if len(seen_comment_ids) >= max_comments:
                    documents_unvisited += len(documents) - index
                    break

                fetched = await self._fetch(context, document, recorder=recorder)
                if fetched is None:
                    continue
                documents_retrieved += 1

                for comment in fetched:
                    if comment.id in seen_comment_ids:
                        diagnostics.record_suppression(
                            step=self.name,
                            reason=SuppressionReason.DUPLICATE_COMMENT,
                            count=1,
                        )
                        continue
                    if len(seen_comment_ids) >= max_comments:
                        comments_dropped_for_budget += 1
                        continue
                    seen_comment_ids.add(comment.id)
                    sink.append(comment)

        # Two different units, so two entries: a suppression's count must
        # mean one thing.
        if comments_dropped_for_budget:
            diagnostics.record_suppression(
                step=self.name,
                reason=SuppressionReason.BUDGET_MAX_COMMENTS,
                count=comments_dropped_for_budget,
                detail=f"comments dropped at the {max_comments}-comment budget",
            )
        if documents_unvisited:
            diagnostics.record_suppression(
                step=self.name,
                reason=SuppressionReason.BUDGET_MAX_COMMENTS,
                count=documents_unvisited,
                detail=f"documents never fetched at the {max_comments}-comment budget",
            )
        if comments_dropped_for_budget or documents_unvisited:
            diagnostics.raise_flag(ResearchFlag.BUDGET_LIMIT_REACHED)

        context.data["polling_comments"] = polling_comments
        context.data["topical_comments"] = topical_comments
        context.data["comments"] = polling_comments + topical_comments
        context.data["posts_retrieved"] = documents_retrieved

        statistics = context.research.statistics
        statistics["documents_retrieved"] = documents_retrieved
        statistics["comments_retrieved"] = len(polling_comments) + len(topical_comments)
        statistics["polling_comments_retrieved"] = len(polling_comments)
        statistics["topical_comments_retrieved"] = len(topical_comments)
        context.research.status = ResearchStatus.ANALYZING
        return context

    async def _fetch(
        self,
        context: PipelineContext,
        document: SourceDocument,
        *,
        recorder: SourceHealthRecorder,
    ) -> Sequence[Comment] | None:
        """One comment-tree fetch. ``None`` means the call failed and was recorded."""
        adapter = context.source.name
        try:
            comments = await context.source.fetch_comments(document)
        except Exception as exc:  # one bad thread must not end the retrieval pass
            kind = failure_kind(exc)
            logger.warning(
                "retrieval: %s failed to fetch comments for %s (%s): %s",
                adapter,
                document.id,
                kind,
                exc,
            )
            recorder.record_failure(adapter, kind=kind)
            context.research.diagnostics.record_suppression(
                step=self.name,
                reason=SuppressionReason.RETRIEVAL_SOURCE_FAILURE,
                count=1,
                detail=kind,
            )
            return None
        recorder.record_success(adapter)
        return comments
