"""Core domain types.

Pure data. No I/O, no framework imports — see the import-boundary test in
tests/unit/test_architecture.py.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl

from tripfinder.domain.config import ResearchConfig


class EntityType(StrEnum):
    """The tier a recommendation target belongs to (PROJECT.md §7, plan §5)."""

    COUNTRY = "country"
    REGION = "region"
    STATE = "state"
    CITY = "city"
    TOWN = "town"
    PARK = "park"
    BEACH = "beach"
    TRAIL = "trail"
    ISLAND = "island"
    OTHER = "other"


class Stance(StrEnum):
    """Signed opinion polarity (plan §2.3). Only ``POSITIVE`` counts toward supporters."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    MENTION_ONLY = "mention_only"


class ReasonCode(StrEnum):
    """Why a comment's analysis came out the way it did (plan §5, §2.12).

    Replaces the free-text ``reasoning`` sentence Phase 8 asked for. That
    sentence was 50.2 % of the analysis response payload, for a string no
    user and no later step ever read.

    **Shrinking it bought no measurable latency**, which is not what 14.6a
    expected. Median batch latency after the change is 25.6 s against 23.2 s
    measured before it, both at ``effort=low``; the run's speed came from
    dispatching batches concurrently, not from a smaller response. The
    numbers are not perfectly comparable — one batch in isolation against a
    median of 42 under concurrent load — but they do not support "a smaller
    payload is faster", so this docstring no longer claims it.

    What the change is worth is the rest of this docstring. Prose can
    only be read one item at a time; an enum can be counted, which is what
    plan §0.1 needs from it: a run that returns little should be able to say
    whether its corpus was off topic, out of scope, or simply mute, rather
    than leaving "few recommendations" and "we could not see" looking alike.

    ``OTHER`` exists because a forced choice between wrong categories is
    worse than an honest miss. It is counted like the rest, so a category
    the corpus needs and this set lacks shows up as a rising number rather
    than as quietly mislabelled comments (Phase 15 reads it).
    """

    RECOMMENDS = "recommends"
    """Names one or more places, in scope, as an answer to the question."""

    RECOMMENDS_OUT_OF_SCOPE = "recommends_out_of_scope"
    """A real recommendation for somewhere the query did not ask about."""

    CRITERION_MISMATCH = "criterion_mismatch"
    """On topic and naming places, but not on the criteria — §4.7's downgrade, per comment."""

    ADVISES_AGAINST = "advises_against"
    """Names places in order to warn about them. Evidence, with a negative stance."""

    MENTION_ONLY = "mention_only"
    """Names places without judging them — logistics, a correction, an aside."""

    NO_PLACE_NAMED = "no_place_named"
    """On topic, but recommends nothing nameable: agreement, a joke, a meta-remark."""

    ASKS_A_QUESTION = "asks_a_question"
    """The commenter is asking, not answering. Common in the threads worth reading."""

    OFF_TOPIC = "off_topic"
    """Not about the topic at all."""

    UNUSABLE = "unusable"
    """Too short, not English, or otherwise unreadable (plan §6 drops non-English)."""

    OTHER = "other"
    """None of the above. Counted, so that a gap in this set is visible."""


class ContextType(StrEnum):
    """Whether a SourceDocument is a fair vote or merely topical (plan §4.5)."""

    POLLING = "polling"
    TOPICAL = "topical"


class ResearchStatus(StrEnum):
    """Research lifecycle states (plan §7)."""

    PENDING = "pending"
    UNDERSTANDING = "understanding"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"
    DISCOVERING = "discovering"
    RETRIEVING = "retrieving"
    ANALYZING = "analyzing"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    COMPLETED_PARTIAL = "completed_partial"
    COMPLETED_DEGRADED = "completed_degraded"
    SOURCE_UNAVAILABLE = "source_unavailable"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Entity(BaseModel):
    """A generic travel destination/recommendation target (PROJECT.md §7)."""

    id: UUID = Field(default_factory=uuid4)
    canonical_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)


class User(BaseModel):
    """The source-community author, required for independent-opinion dedup (PROJECT.md §7)."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    display_name: str | None = None


UNKNOWN_USER_ID = "[deleted]"
"""The identity a source uses for a deleted or anonymized author.

Every such comment collapses onto this one id, so it cannot be used as a
deduplication key (plan §4.6 step 9, `PROJECT.md` §16) — doing so would fold
unrelated people into a single voter. Adapters map deleted/missing authors
to this value; it lives in ``domain`` because both a source adapter and a
pipeline step need the same constant to agree on what "unknown" means.
"""


class SourceDocument(BaseModel):
    """A source post/thread (PROJECT.md §7). ``context_type`` is set by triage (plan §4.7)."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    title: str
    url: HttpUrl
    subreddit: str | None = None
    created_at: datetime
    comment_count: int = Field(ge=0)
    context_type: ContextType | None = None


class Comment(BaseModel):
    """An individual source comment (PROJECT.md §7)."""

    id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    body: str
    created_at: datetime
    permalink: HttpUrl
    score: int | None = None
    """The community's vote total, where the source reports one (plan §2.12).

    Used only to decide *which* comments of a thread are worth the analysis
    budget when it cannot buy all of them (plan §4.6 step 6) — never to
    weight an opinion. Plan §4.2 counts independent users, and letting an
    upvote count twice would be exactly the popularity bias `PROJECT.md` §16
    deduplicates against.

    ``None`` means the source did not say, which is not the same as zero: a
    comment nobody voted on and a comment whose score we never learned are
    different facts, and only one of them is evidence about the comment.
    """


class Opinion(BaseModel):
    """A normalized opinion derived from a comment (PROJECT.md §7, plan §2.3)."""

    id: UUID = Field(default_factory=uuid4)
    comment_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    stance: Stance
    strength: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    criteria_matches: list[str] = Field(default_factory=list)
    timestamp: datetime
    confidence: float = Field(ge=0.0, le=1.0)


class GeoScope(BaseModel):
    """The geographic bound of a research question (plan §6), e.g. a country."""

    type: str = Field(min_length=1)
    value: str = Field(min_length=1)


class ResearchPlan(BaseModel):
    """Query Understanding's confident outcome (plan §6): a research is ready to discover."""

    normalized_query: str = Field(min_length=1)
    scope: GeoScope
    entity_granularity: EntityType
    granularity_confidence: float = Field(ge=0.0, le=1.0)
    topic: str = Field(min_length=1)
    criteria: list[str] = Field(default_factory=list)
    seed_queries: list[str] = Field(default_factory=list)
    candidate_subreddits: list[str] = Field(default_factory=list)


class ReusedAnswer(BaseModel):
    """This run did not do the work: it is showing an earlier run's answer (plan §2.15).

    The two fields travel together on purpose. Plan §2.15 rule 1 is that a
    reused answer says *when it was produced*, and the way to make a label
    impossible to omit is to make the fact and the date one object — there
    is no state in which a client knows an answer was reused and does not
    also have the date to say so.

    ``answered_at`` is the **original** run's date, never this one's, and
    never a date inherited from a run that was itself reusing: only a run
    that actually did the work may answer for a later question, so the chain
    is one link long by construction (``AnswerReuseStep``).
    """

    research_id: UUID
    """The run whose answer this is — reachable at its own URL since 14.9."""

    answered_at: datetime
    """When that run was started, which is when this answer was produced."""


class ClarificationOption(BaseModel):
    """One choice offered back to the user, mapped to a candidate granularity (plan §6)."""

    label: str = Field(min_length=1)
    entity_granularity: EntityType


class ClarificationRequest(BaseModel):
    """Query Understanding's ambiguous outcome (plan §2.4, §6): ask before guessing."""

    question: str = Field(min_length=1)
    options: list[ClarificationOption]
    allow_grouped: bool = True


class GranularityConfidence(BaseModel):
    """One tier Query Understanding considered plausible, with its confidence (plan §6)."""

    entity_granularity: EntityType
    confidence: float = Field(ge=0.0, le=1.0)


class PendingPlan(BaseModel):
    """What Query Understanding learned before confidence fell short of a plan (plan §6).

    Not user-facing — ``ClarificationRequest`` is what the API shows. This is
    persisted so ``POST /research/{id}/clarify`` can build the final
    ``ResearchPlan`` once the user picks a granularity, without re-running the
    LLM call that already answered everything except which tier to target.
    """

    normalized_query: str = Field(min_length=1)
    scope: GeoScope | None = None
    topic: str | None = None
    criteria: list[str] = Field(default_factory=list)
    seed_queries: list[str] = Field(default_factory=list)
    candidate_subreddits: list[str] = Field(default_factory=list)
    granularity_candidates: list[GranularityConfidence] = Field(default_factory=list)


class TriageVerdict(StrEnum):
    """Document Triage's three outcomes (plan §4.7)."""

    POLLING = "polling"
    TOPICAL = "topical"
    EXCLUDE = "exclude"


class TriageDecidedBy(StrEnum):
    """Which half of triage decided — rules short-circuit the AI call (plan §4.7)."""

    RULE = "rule"
    AI = "ai"


class TriageDecision(BaseModel):
    """One document's verdict *and its reason* (plan §4.7 mitigation 1).

    Persisted for every triaged document, so a thin result is always
    explainable rather than merely thin (plan §0.1).
    """

    document_id: str = Field(min_length=1)
    verdict: TriageVerdict
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    decided_by: TriageDecidedBy
    scope_match: bool = True
    granularity_match: bool = True
    criterion_match: bool = True
    downgraded_for_low_confidence: bool = False


class EntityResolutionMethod(StrEnum):
    """Which half of entity resolution settled a name (plan §4.6 step 8)."""

    RULE = "rule"
    AI = "ai"


class EntityResolutionOutcome(BaseModel):
    """What became of one surface form the comments used (plan §4.6 step 8).

    One entry per *distinct* way of writing a name, not per mention —
    ``occurrences`` says how many mentions used it. That keeps the record
    bounded by vocabulary rather than corpus size while still naming every
    form the run failed to resolve.

    ``entity_id is None`` is the case `PROJECT.md` §15 is about: the name
    was **not** merged into anything, and ``reason`` says why not.
    """

    surface_form: str = Field(min_length=1)
    entity_type: EntityType
    occurrences: int = Field(gt=0)
    entity_id: str | None = None
    canonical_name: str | None = None
    decided_by: EntityResolutionMethod
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)


class SourceHealth(BaseModel):
    """Per-adapter call accounting for one research (plan §8.1).

    Persisted into the snapshot so a degraded run can always name the
    adapter and failure kind that degraded it.
    """

    adapter: str = Field(min_length=1)
    calls_attempted: int = Field(ge=0)
    calls_succeeded: int = Field(ge=0)
    calls_failed: int = Field(ge=0)
    failure_kinds: dict[str, int] = Field(default_factory=dict)
    success_rate: float = Field(ge=0.0, le=1.0)


class SourceOutcome(StrEnum):
    """The §8.1 outcome rules' verdict on whether the corpus can be trusted."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class SuppressionReason(StrEnum):
    """The fixed vocabulary of ways this pipeline drops evidence (plan §0.1 rule 1).

    Every value names a decision the system made *about* the corpus. A
    reason that reaches the API lets the user tell "we did not look" apart
    from "there was nothing to find".
    """

    TRIAGE_EXCLUDED = "triage_excluded"
    TRIAGE_NOT_POLLING = "triage_not_polling"
    TRIAGE_NO_VERDICT = "triage_no_verdict"
    TOPICAL_UNOPENED = "topical_unopened"
    BUDGET_MAX_TOTAL_POSTS = "budget_max_total_posts"
    BUDGET_MAX_COMMENTS = "budget_max_comments"
    BUDGET_MAX_AI_ANALYSIS_ITEMS = "budget_max_ai_analysis_items"
    BUDGET_MAX_SEARCH_QUERIES = "budget_max_search_queries"
    BUDGET_MAX_RESEARCH_DURATION = "budget_max_research_duration"
    RETRIEVAL_SOURCE_FAILURE = "retrieval_source_failure"
    DUPLICATE_COMMENT = "duplicate_comment"
    PREFILTER_TOO_SHORT = "prefilter_too_short"
    PREFILTER_EMPTY_BODY = "prefilter_empty_body"
    ANALYSIS_NO_RESULT = "analysis_no_result"
    ANALYSIS_FABRICATED_QUOTE = "analysis_fabricated_quote"
    ANALYSIS_BATCH_FAILED = "analysis_batch_failed"
    ENTITY_AMBIGUOUS = "entity_ambiguous"
    ENTITY_UNRESOLVED = "entity_unresolved"
    ENTITY_OFF_GRANULARITY = "entity_off_granularity"
    ENTITY_RESOLUTION_NO_RESULT = "entity_resolution_no_result"
    AGGREGATION_BELOW_RELEVANCE_THRESHOLD = "aggregation_below_relevance_threshold"
    SUMMARIZATION_NO_EVIDENCE = "summarization_no_evidence"
    SUMMARIZATION_NO_RESULT = "summarization_no_result"
    SUMMARIZATION_FABRICATED_QUOTE = "summarization_fabricated_quote"


class Suppression(BaseModel):
    """A count of evidence dropped by one step for one reason (plan §0.1 rule 1)."""

    step: str = Field(min_length=1)
    reason: SuppressionReason
    count: int = Field(ge=0)
    detail: str | None = None


class QuoteVerdict(StrEnum):
    """What became of one non-exact supporting quote (plan §2.12.1)."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class QuoteVerification(BaseModel):
    """One borderline anti-fabrication decision, kept for review (plan §2.12.1).

    Written for every verification that was **not** an exact substring
    match — accepted and rejected alike. Only recording the rejections would
    answer half the question: the threshold is worth revisiting both for what
    it dropped just below the line and for what it admitted just above it.
    """

    comment_id: str = Field(min_length=1)
    mention_text: str = Field(min_length=1)
    """The surface form the discarded or kept mention named."""

    claimed_quote: str = Field(min_length=1)
    matched_span: str
    """The closest stretch of the comment, normalised. Empty when nothing matched."""

    similarity: float = Field(ge=0.0, le=1.0)
    verdict: QuoteVerdict


class ResearchFlag(StrEnum):
    """Conditions that make a result set worth questioning (plan §4.7 mitigation 3)."""

    LOW_POLLING_DOCUMENT_RATIO = "low_polling_document_ratio"
    BUDGET_LIMIT_REACHED = "budget_limit_reached"


class FailureKind(StrEnum):
    """Named causes for a ``failed`` research (plan §0.1 rule 3).

    "Something went wrong" is the wording §0.1 exists to forbid: it leaves
    the user unable to tell a broken run from a quiet one. Each value here
    points at a different remedy — fix the credential, wait and retry, fix
    the request, or distrust the model's output.
    """

    LLM_CREDENTIAL = "llm_credential"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_REQUEST_REJECTED = "llm_request_rejected"
    LLM_INVALID_RESPONSE = "llm_invalid_response"
    UNEXPECTED_ERROR = "unexpected_error"
    """A non-LLM exception the worker caught (plan §10 Phase 13's error contract) — the
    mirror of the LLM failures above for everything ``PipelineRunner`` does not itself
    convert. Without this, a crashing step left the research stuck at ``pending`` forever
    (plan §0.1: a failure must never masquerade as a finding — here, as a queued one)."""


class ResearchFailure(BaseModel):
    """Why a research ended ``failed``, and where (plan §0.1 rules 1 and 3).

    Persisted and exposed rather than logged. A run that failed for want of
    a credential produced no evidence at all, and this is what keeps that
    fact attributable instead of arriving as an empty result set.
    """

    kind: FailureKind
    step: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ResearchDiagnostics(BaseModel):
    """Everything §0.1 requires a research to be able to explain about itself.

    Not debug output: this is the evidence trail that keeps a suppressed run
    distinguishable from a genuinely thin one, and it is exposed through the
    API rather than left in the logs.
    """

    source_health: list[SourceHealth] = Field(default_factory=list)
    source_outcome: SourceOutcome | None = None
    triage_decisions: list[TriageDecision] = Field(default_factory=list)
    entity_resolutions: list[EntityResolutionOutcome] = Field(default_factory=list)
    quote_verifications: list[QuoteVerification] = Field(default_factory=list)
    """Non-exact anti-fabrication decisions (plan §2.12.1), for Phase 15 to calibrate against."""
    suppressions: list[Suppression] = Field(default_factory=list)
    flags: list[ResearchFlag] = Field(default_factory=list)
    failure: ResearchFailure | None = None
    """Set only for a ``failed`` run — the named cause §0.1 rule 3 requires."""

    def record_suppression(
        self,
        *,
        step: str,
        reason: SuppressionReason,
        count: int,
        detail: str | None = None,
    ) -> None:
        """Append a suppression, coalescing repeats of the same step+reason+detail."""
        if count <= 0:
            return
        for existing in self.suppressions:
            if existing.step == step and existing.reason == reason and existing.detail == detail:
                existing.count += count
                return
        self.suppressions.append(
            Suppression(step=step, reason=reason, count=count, detail=detail)
        )

    def raise_flag(self, flag: ResearchFlag) -> None:
        if flag not in self.flags:
            self.flags.append(flag)

    def record_failure(self, *, kind: FailureKind, step: str, detail: str) -> None:
        """Name the cause of a failed run. The first cause wins.

        A failed run has no later steps, so in practice there is one cause;
        should that ever change, the original failure is the one that
        explains the missing evidence.
        """
        if self.failure is None:
            self.failure = ResearchFailure(kind=kind, step=step, detail=detail)


class Result(BaseModel):
    """One ranked entity in a completed research (PROJECT.md §7, plan §4)."""

    entity_id: str = Field(min_length=1)
    entity_name: str = Field(min_length=1)
    supporter_count: int = Field(ge=0)
    share: float = Field(ge=0.0)
    respondent_pool_size: int = Field(ge=0)
    discussion_count: int = Field(ge=0)
    weighted_score: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str | None = None
    evidence_permalinks: list[HttpUrl] = Field(default_factory=list)


class Research(BaseModel):
    """One execution of a user's query (PROJECT.md §7). Never silently overwritten."""

    id: UUID = Field(default_factory=uuid4)
    original_query: str = Field(min_length=1)
    normalized_query: str | None = None
    created_at: datetime
    status: ResearchStatus
    research_config: ResearchConfig = Field(default_factory=ResearchConfig)
    statistics: dict[str, int] = Field(default_factory=dict)
    results: list[Result] = Field(default_factory=list)
    """Strong recommendations only — ``supporterCount >= minimumIndependentUsers``,
    capped at ``maxStrongResults`` (plan §4.4). Never padded."""
    weak_results: list[Result] = Field(default_factory=list)
    """Everything ranked but not shown as a headline result: below the
    independent-user threshold, or beyond the strong-results cap. Persisted
    rather than discarded (plan §4.4 "may appear in a separate weaker
    signals section") — nothing computed here is silently dropped."""
    diagnostics: ResearchDiagnostics = Field(default_factory=ResearchDiagnostics)
    clarification: ClarificationRequest | None = None
    """Set only while ``status`` is ``needs_clarification`` — the question the API shows
    the user (plan §6). The API layer reads this; it does not derive it from ``pending_plan``."""
    pending_plan: PendingPlan | None = None
    """Not user-facing. What Query Understanding learned before it asked for clarification;
    ``POST /research/{id}/clarify`` uses it to build the final plan (plan §6)."""
    resume_plan: ResearchPlan | None = None
    """Set only when a clarified research is queued to resume mid-pipeline (plan §6): the
    worker seeds it straight into the resumed run's context and skips Query Understanding
    and Preflight entirely, since both already ran before the research paused."""
    plan: ResearchPlan | None = None
    """The plan this run actually ran against, kept so the run can be found again (plan §2.15).

    ``resume_plan`` looks similar and is not the same thing: that one is a
    *instruction to a worker*, set on the clarification path only and
    meaningless once the run is over. This is the run's record of what its
    question was understood to mean, stamped on every run that got past
    Query Understanding, and it is what ``plan_fingerprint`` is computed
    from."""
    plan_fingerprint: str | None = None
    """``plan_fingerprint(self.plan)`` — the reuse key, stored so it can be indexed.

    Derived, and stored anyway: a fingerprint recomputed at query time
    cannot be looked up in a database, and recomputing it for every row of a
    growing table to answer one question is the shape of a feature that gets
    switched off later."""
    reused: ReusedAnswer | None = None
    """Set when this run answered from an earlier one instead of doing the work (plan §2.15).

    Present on the API in every place this run's answer is shown, and the
    reason the frontend can never render a six-month-old ranking as though
    it were produced today."""


HALTING_STATUSES: frozenset[ResearchStatus] = frozenset(
    {
        ResearchStatus.NEEDS_CLARIFICATION,
        ResearchStatus.REJECTED,
        ResearchStatus.SOURCE_UNAVAILABLE,
        ResearchStatus.FAILED,
        ResearchStatus.CANCELLED,
    }
)
"""States from which no further pipeline step may run (plan §7).

``source_unavailable`` is here for the reason §8.1 gives: once every adapter
has failed there is no evidence, so continuing would only build a results
object that must not exist.
"""


def is_halting(status: ResearchStatus) -> bool:
    """Whether the pipeline must stop rather than run its remaining steps."""
    return status in HALTING_STATUSES
