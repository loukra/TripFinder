"""Research budget and floor configuration (plan §1.1).

Every value here is config, not a constant buried in a step. Each research
persists the ``ResearchConfig`` it actually ran with (PROJECT.md §21).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ResearchBudget(BaseModel):
    """Hard limits on how much a single research is allowed to cost (plan §1.1)."""

    max_search_queries: int = Field(default=20, gt=0)
    max_posts_per_query: int = Field(default=40, gt=0)
    max_total_posts: int = Field(default=300, gt=0)
    max_comments: int = Field(default=12000, gt=0)
    max_comments_per_document: int = Field(default=400, gt=0)
    """How much of one thread the corpus may consist of (plan §2.14.2).

    Breadth, not depth. The measured run took comments in document order
    until the 4000-comment budget ran out, which filled the corpus from 13
    of 25 polling threads and left the other 12 — and all 30 topical ones —
    unopened. Doubling the analysis budget on that corpus *lowered* the
    yield, from 0.496 respondents per analysed comment to 0.427, because a
    deeper sample of the same threads is mostly the same people again.

    200 x 300 documents is why ``max_comments`` is 12000: the cap only
    helps if there is budget left for the threads it frees up.
    """
    topical_quota: float = Field(default=0.0, ge=0.0, le=1.0)
    """The share of each budget reserved for topical material (plan §4.5).

    §4.5 is explicit: *"Topical contexts consume only leftover budget, since
    they cannot change the ranking."* This was briefly 0.15 — a reservation
    rather than leftovers — on the reasoning that arrival-order processing
    cannot express "polling first". The measured consequence was that
    topical material took exactly its 15%: 1800 of 4024 admitted comments,
    and 1341 of 2231 opinions were evidence-only, in a run whose top result
    reached 46 supporters against a target of 100.

    **Nothing consumes that corpus.** §4.5 keeps topical material for two
    jobs, explanations and displayed counter-evidence. Phase 12's
    explanations draw their quotes from ``counted_resolutions`` — the
    polling corpus — and ``evidence_opinions`` is written by user
    deduplication and read by no step, no API field and no view. Until one
    of those two jobs is built, a non-zero quota buys fetches, analysis
    calls and entity resolutions whose output reaches nobody.

    Raising it again is a deliberate act: it takes budget from the corpus
    that decides the ranking, and §4.5 says that is the wrong direction
    while polling contexts are scarce.
    """

    max_ai_analysis_items: int = Field(default=8000, gt=0)
    """The analysis corpus cap (plan §2.14.1).

    5000, from the third measurement. The second one is why it is not 3000:
    2490 analysed comments produced a pool of only 669, because the split
    was not applied to *this* budget and roughly 770 of those calls went to
    topical material §4.5 forbids from entering the pool. Counted comments
    therefore received about 1731 of them, and 1731 -> 669 is a yield of
    0.386.

    With the split fixed, 5000 gives the counted corpus 4250 and a projected
    pool near 1640. The top result held 8.7 % of that run's pool — a share
    that has fallen as the corpus broadened, 13.4 % to 10.3 % to 8.7 % — so
    the margin is deliberate: 8.7 % of 1640 is 142, and even 7 % clears 100.

    Time is still not what this spends. Two consecutive runs stopped at
    ``budget_limit_reached`` with no batch refused for the deadline.
    """
    max_research_duration_seconds: int = Field(default=180, gt=0)
    """The promise about the whole research (plan §2.12.2, §2.14.1).

    Lowered from 300 s, and it is now the **binding** limit rather than the
    one nothing reached. Every other budget above was raised past what three
    minutes can consume, deliberately: breadth is what the metric wants, and
    the honest way to buy it is to fan out as wide as the clock allows and
    then stop. Two measured runs in a row ended at ``budget_limit_reached``
    with not one batch refused for time, which means the numbers, not the
    wait, were what held them back.

    A run that stops here is ``completed_partial`` and says so (§7.1). That
    is the correct description: what was read was read properly, and the
    corpus is a real but incomplete sample.
    """
    tail_reserve_seconds: int = Field(default=40, ge=0)
    """Subtracted from the duration budget to derive the dispatch deadline (plan §2.12.2).

    The limit gates what may still be *started*, never what may finish: a
    request is billed the moment it is sent, so abandoning its response buys
    no saving, only a smaller sample. Work already in flight is therefore
    always awaited, which means the deadline alone would overrun the budget
    by up to one batch.

    So the 300 s stays the promise about the whole research and the dispatch
    deadline is derived from it — ``started_at + maxResearchDuration −
    tailReserve`` — rather than the other way round. Stating it the other way
    would make the user's five minutes mean seven, which is the kind of quiet
    redefinition §0.1 exists to prevent.

    60 s is a starting value, not a measured one. Phase 15 calibrates it
    against real runs.
    """

    max_estimated_cost_usd: float = Field(default=0.50, gt=0.0)


class SourceHealthFloors(BaseModel):
    """Below these, a research fails outright rather than reporting (plan §1.1, §8.1)."""

    min_source_success_rate: float = Field(default=0.80, ge=0.0, le=1.0)
    min_posts_retrieved: int = Field(default=10, ge=0)
    min_comments_analyzed: int = Field(default=100, ge=0)


class TriageFloors(BaseModel):
    """Document triage thresholds (plan §1.1, §4.7)."""

    min_comments_per_document: int = Field(default=5, ge=0)
    max_document_age_years: int = Field(default=15, gt=0)
    triage_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    min_polling_document_ratio: float = Field(default=0.15, ge=0.0, le=1.0)


class QueryUnderstandingConfig(BaseModel):
    """Query Understanding thresholds (plan §2.4, §6)."""

    granularity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class PrefilterConfig(BaseModel):
    """Cheap pre-filtering heuristics (plan §4.6 step 6).

    Deliberately only measures substance, never topic: dropping comments for
    not matching keywords is exactly the over-strict filter plan §0.1 warns
    about, and semantic relevance is the §5 analysis call's job.
    """

    min_comment_characters: int = Field(default=40, ge=0)


class EntityResolutionConfig(BaseModel):
    """Entity resolution thresholds (plan §4.6 step 8, `PROJECT.md` §15).

    ``confidence_threshold`` is the floor below which a model-proposed
    canonical name is **not** acted on. `PROJECT.md` §15's "never silently
    merge entities when confidence is too low" is this number plus the
    diagnostics that make the refusal visible.
    """

    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class QuoteVerificationConfig(BaseModel):
    """The anti-fabrication check's tolerance (plan §5, §2.12.1).

    0.90 is a starting threshold with a hand-inspected sample behind it, not
    a measured optimum: of nine discards read against their comments, six
    were formatting misses that this admits and three were genuine
    misattributions that it still rejects. Phase 15 calibrates it from the
    audit trail, which is why every borderline decision is kept.
    """

    similarity_threshold: float = Field(default=0.90, ge=0.0, le=1.0)


class RankingKey(StrEnum):
    """Which computed number decides sort order first (plan §2.5, §4.3).

    ``weightedScore`` can never exceed ``supporterCount`` (plan §4.2), so
    either choice is a legitimate primary key; what must never happen is the
    displayed order disagreeing with the displayed number (plan §2.5) — the
    other of the two is always used as the tiebreak, never a third metric.
    """

    SUPPORTER_COUNT = "supporter_count"
    WEIGHTED_SCORE = "weighted_score"


class RankingConfig(BaseModel):
    """The metric's thresholds and weights (plan §4) — the exact numbers behind
    the headline count.

    ``relevance_threshold`` has no plan-specified default: plan §4.1 defines
    the gate ("relevance >= relevanceThreshold") but leaves the number to
    implementation, the same way every other floor in this file is a
    considered default rather than a hardcoded constant. 0.5 is the
    midpoint of the 0-1 scale §5's ``topic_relevance``/``criterion_relevance``
    report on — evaluation (plan Phase 15) is expected to tune it.
    """

    relevance_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    decay_per_year: float = Field(default=0.10, ge=0.0)
    min_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    ranking_key: RankingKey = Field(default=RankingKey.SUPPORTER_COUNT)
    minimum_independent_users: int = Field(default=5, ge=0)
    max_strong_results: int = Field(default=5, gt=0)


class ResearchConfig(BaseModel):
    """The full configuration a research run persists (PROJECT.md §21)."""

    budget: ResearchBudget = Field(default_factory=ResearchBudget)
    source_health_floors: SourceHealthFloors = Field(default_factory=SourceHealthFloors)
    triage_floors: TriageFloors = Field(default_factory=TriageFloors)
    query_understanding: QueryUnderstandingConfig = Field(default_factory=QueryUnderstandingConfig)
    prefilter: PrefilterConfig = Field(default_factory=PrefilterConfig)
    entity_resolution: EntityResolutionConfig = Field(default_factory=EntityResolutionConfig)
    quote_verification: QuoteVerificationConfig = Field(default_factory=QuoteVerificationConfig)
    ranking: RankingConfig = Field(default_factory=RankingConfig)
