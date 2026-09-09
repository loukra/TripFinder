# Implementation Plan — Opinion-Based Travel Research Engine

**Status:** Ready for implementation
**Date:** 2026-09-09
**Companion to:** `PROJECT.md`

---

## 0. How to use this document

`PROJECT.md` is the **product and architecture brief**. It states intent, principles, and
constraints. It remains authoritative for *why*.

`implementation-plan.md` (this file) is the **executable brief**. It resolves every decision
`PROJECT.md` deferred, corrects the design flaws found during review, and defines the phase
sequence an implementing agent follows.

**Precedence rule:** where the two documents conflict, this file wins, and §2 records exactly
which `PROJECT.md` sections it overrides and why. Nothing here contradicts `PROJECT.md`'s
architectural principles (§6) or engineering constraints (§29) — those are untouched and remain
binding.

**Working agreement for the implementing agent:**

1. Implement **one phase at a time**. Never skip ahead.
2. Finish each phase to the Definition of Done (§12) before starting the next.
3. Report using the template in §12, then **stop and wait**.
4. If a phase reveals that this plan is wrong, say so and propose an amendment. Do not silently
   deviate.

### 0.1 Standing principle — a failure must never masquerade as a finding

This project's only real asset is trustworthiness. The number on the results page is worth
something **only** if the user can tell the difference between *"few people recommend this"* and
*"we failed to look properly."* Those two outcomes produce identical-looking output unless the
system is built to keep them apart.

Three instances are already specified — a source outage (§2.7), a biased thread inflating the
denominator (§2.8), and over-strict triage starving the corpus (§4.7). They are the same bug wearing
different clothes, and there will be more. `PROJECT.md` §29 forbids fabricating evidence; this is its
mirror — **fabricating the absence of evidence** — and it is the more dangerous of the two, because
nothing about the output looks wrong.

**Binding on every step that can drop, exclude, downweight, or fail to retrieve evidence:**

1. **Record what was suppressed and why.** Counts and reasons, persisted in the research snapshot.
2. **Expose it.** Suppression counts reach the API and are visible in the UI, not just the logs.
3. **Make thin results attributable.** Any short or empty result set must name its cause.
4. **Never share wording.** A degraded outcome may not be described in the same words as a genuine
   one — the §7.1 status table exists to enforce this.
5. **Test the distinction.** Every suppressing step needs a test proving a suppressed run and a
   genuinely thin run are distinguishable in the output. This is the regression that reintroduces
   the bug every time.

When adding any step not currently in §4.6, apply this checklist before writing its tests.

---

## 1. Locked decisions

Everything `PROJECT.md` §31 deferred is decided here. These are fixed; changing one is an
amendment, not an implementation detail.

| Area | Decision | Rationale |
|---|---|---|
| Backend | **Python 3.12.14** (pinned in `.python-version`), FastAPI, Pydantic v2 | Strongest ecosystem for the analysis/eval work; Pydantic gives the validated structured output `PROJECT.md` demands throughout |
| Frontend | Next.js (App Router), React, TypeScript | Results page needs charts, polling, progress state |
| Database | PostgreSQL 16 | Snapshot persistence with JSONB for pipeline payloads |
| ORM / migrations | SQLAlchemy 2.x + Alembic | |
| Python toolchain | **uv** — Python version, venvs, dependencies | One tool replacing pyenv + pip + venv. Installed; 3.12.14 pinned |
| Job queue | **Postgres-backed job table + polling worker. No Redis.** | One less service; local-first; `PROJECT.md` §29 "prefer simple solutions" |
| LLM provider | **OpenAI**, behind an `LLMProvider` port | User decision. Port keeps §13's replaceability |
| Default model | `gpt-5-mini` for analysis, larger tier for query understanding + summaries | ~$0.15/research at balanced budget |
| Model config | Model IDs in config only. **Never in the domain layer** | `PROJECT.md` §13 |
| Source | **Arctic Shift only** (`https://arctic-shift.photon-reddit.com`) | No API key or approval needed. Official Reddit API requires manual approval since Nov 2025 |
| Source port | `SourceAdapter` port **is still built**; only one adapter implements it | Preserves §10 without speculative second adapter |
| Local dev | **Hybrid** — Postgres in Docker, backend/worker/frontend native. Compose `full` profile runs everything | Hot reload where you edit; hermetic Postgres for tests |
| Testing | pytest (backend), Vitest + Playwright (frontend) | |
| Lint / format / types | ruff + mypy (strict) backend; eslint + tsc frontend | |

### 1.1 Research budget defaults

```
maxSearchQueries       12
maxPostsPerQuery       25
maxTotalPosts         120
maxComments          4000    # retrieved, before pre-filter
maxAIAnalysisItems   1000    # after pre-filter, sent to the LLM
maxResearchDuration   300s
maxEstimatedCostUSD  0.50    # hard stop
```

Source-health floors (§8.1) — a research that breaches these **fails**, it does not report:

```
minSourceSuccessRate  0.80   # fraction of source calls that must succeed
minPostsRetrieved       10   # below this the corpus is too thin to rank
minCommentsAnalyzed    100   # below this the denominator is meaningless
```

Triage floors (§4.7):

```
minCommentsPerDocument      5
maxDocumentAgeYears        15
triageConfidenceThreshold 0.6   # below this, downgrade to topical
minPollingDocumentRatio  0.15   # below this, flag the research
```

Target: ~2–4 minutes, ~$0.15/research. Every value is config, not a constant in code. Each
research **persists the budget it actually ran with** (`PROJECT.md` §21).

### 1.2 Deferred, deliberately

- **Additional source adapters** (official Reddit API, web search, travel forums, YouTube) —
  deferred as *future work*, not rejected. `PROJECT.md` §3 makes multi-source the roadmap, and the
  `SourceAdapter` port exists to serve it. The MVP ships one adapter because one is enough to
  validate the product, not because the port is speculative. Adding the next source must not
  require changes to `domain/`, `ranking/`, or the pipeline steps — Phase 15 should include a
  paper exercise confirming that.
- Embeddings-based pre-filtering — Phase 7 ships heuristic pre-filtering first; add embeddings
  only if evaluation (Phase 15) shows the filter is the weak stage.
- Authentication, multi-user, personalization — out of scope per `PROJECT.md` §2.

---

## 2. Corrections to PROJECT.md

Issues found in review. Each has a resolution that is binding on implementation.

### 2.1 The headline percentage was undefined — **now specified in §4**

`PROJECT.md` §19 says the percentage is "the share of independent users recommending the entity
within the relevant analyzed population" but never defines that population. The worked example
(47/24/15 users → 42%/21%/14%) implies a denominator of ~112, i.e. all users with any counted
opinion including entities outside the top 5 — self-consistent, but never stated.

A second problem: one user can recommend three destinations, so **shares do not sum to 100%**.
`PROJECT.md` §24's "distribution chart" would therefore be actively misleading as a pie chart.

**Resolution:** counts lead, percentage is secondary and explicitly labeled. Exact math in §4.
Bars only, never a pie. Every percentage is rendered with its denominator visible.

### 2.2 Pipeline steps 6/7/9 as separate LLM passes — **merged into one call**

`PROJECT.md` §12 lists Semantic Relevance Analysis (6), Entity Extraction (7), and Opinion
Extraction (9) as separate steps. All three read the same comment text. Implementing them as three
LLM passes triples cost and latency for no quality gain.

**Resolution:** they remain three **logical concerns with independent tests**, implemented as a
**single structured-output call per comment batch** producing one `CommentAnalysis` record. §5
gives the schema.

### 2.3 Opinion polarity was missing — **stance is now signed**

`PROJECT.md` §7 gives `Opinion` a `recommendation strength` but no polarity. "Alaska is overrated,
everyone recommends it and it's a letdown" would be extracted as an Alaska *recommendation* and
inflate its score.

**Resolution:** `stance` is an explicit enum (`positive` / `negative` / `mixed` / `mention_only`).
**Only `positive` counts toward supporter counts.** Negative and mixed are stored, surfaced as
counter-evidence in the UI, and never silently discarded.

### 2.4 Mixed entity granularity — **query declares it, ambiguity asks**

"Most underrated US destinations" returns Alaska (state), Zion (national park), and Marfa (town).
Ranking a state against a town is not a meaningful comparison, and no amount of correct
aggregation fixes it.

**Resolution:** a well-formed research question is granularity-deterministic ("most underrated
*states*", "most beautiful *small towns*"). Query Understanding extracts a target
`entityGranularity` plus a confidence. Below threshold, the research enters
**`needs_clarification`** and asks the user rather than guessing. See §6.

### 2.5 Ranking key vs. displayed number could disagree — **rank on what you display**

If ranking sorts by `weightedScore` (time-decayed, strength-weighted) while the UI displays raw
supporter counts, the page can render `1. Alaska 47 people / 2. Oregon 52 people` and look broken.

**Resolution:** `rankingKey` is config, **defaulting to `supporterCount`**, so displayed order and
displayed number always agree. `weightedScore` is still computed, persisted, tested, and shown as a
secondary column — flip the config once evaluation justifies it. Time weighting is fully
implemented per `PROJECT.md` §17; it just isn't the primary sort on day one.

### 2.8 Not every thread is a poll — **only polling contexts vote**

`PROJECT.md` treats every retrieved comment as potential evidence of equal standing. But a thread
titled *"Alaska is so underrated, anyone else?"* pre-selects its own answer: nobody who prefers
Oregon clicks it. The 50 people agreeing are expressing real opinions, and none of them is a vote on
the ranking question.

The failure mode is subtler than double-counting. If such a thread's Alaska mentions are excluded
but its 50 users stay in the respondent pool `P`, then *other* entities are penalised — Oregon drops
from 24/112 to 24/162 because of a thread it never appeared in. A biased thread must leave the
ranking through **both numerator and denominator**, or not at all.

**Resolution:** classify each `SourceDocument` as a **polling context** or a **topical context**.
Only polling contexts contribute to ranking. Topical contexts are retained and used for explanation
and counter-evidence. Full rules in §4.5.

### 2.7 Source failure was indistinguishable from absent evidence — **now a hard error**

`PROJECT.md` §20 tells the system to show fewer than five results when evidence is weak, and §29
says external failures should be "recoverable where practical". Neither document distinguishes
**"Reddit genuinely has little to say about this"** from **"our data source was down"**. Both would
surface as a thin result set, and the user could not tell which had happened.

That makes *"We found 2 strong recommendations"* a false statement whenever retrieval was degraded.
§29 forbids inventing evidence; this is the mirror image — **inventing confidence in a negative
result** — and it is worse, because a fabricated absence looks exactly like a real one.

**Resolution:** source health is measured, persisted, and gates the outcome. If every adapter fails,
the research **fails loudly with no results page**. Degraded retrieval produces a distinct
`completed_degraded` status that the UI must not present as a normal answer. Full semantics in §8.1.

### 2.6 Nothing demoable for 13 phases — **walking skeleton at 3.5**

`PROJECT.md` §27 puts the API at Phase 13 and the frontend at Phase 14. That defers all
integration risk to the end and gives no feedback loop.

**Resolution:** insert **Phase 3.5**, a thin API + minimal UI on the fake pipeline. Every
subsequent phase then visibly improves a running product.

### 2.9 The real LLM provider was never shipped — **Phase 7.5 added**

§1 locks OpenAI behind the `LLMProvider` port and §3.1 reserves `ai/` for "openai, fake", but no
phase in §10 ever shipped the OpenAI adapter, and no phase introduced the settings layer that would
hold an API key. Every LLM-consuming phase (5, 6, 8, 9, 12) is fully satisfiable with
`FakeLLMProvider`, so the plan stayed green to Phase 15 without a key ever being required. The
composition root compounded it: `jobs/worker_loop.py` runs `build_fake_pipeline_runner()`, and no
phase said to switch it.

This is a §0.1 problem, not merely a missing task. A run whose LLM calls fail for want of a
credential would otherwise produce an empty analysis — a failure wearing the face of a thin finding.

**Resolution:** insert **Phase 7.5**, which ships the OpenAI adapter, the runtime settings layer,
and provider selection defaulting to fake. **Phase 13** additionally ships the composition-root
switch to the real pipeline.

---

## 3. Architecture

Unchanged from `PROJECT.md` §4–6: **Modular Monolith + Ports & Adapters + Research Pipeline +
Async Jobs**. This plan does not alter it.

### 3.1 Repository layout

```
TripFinder/
├── docker-compose.yml
├── PROJECT.md
├── implementation-plan.md
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── src/tripfinder/
│   │   ├── domain/          # pure. no I/O, no framework imports.
│   │   │   ├── models.py            # Research, Entity, Comment, Opinion, Result
│   │   │   ├── config.py            # ResearchBudget, ResearchConfig
│   │   │   └── ports.py             # SourceAdapter, LLMProvider protocols
│   │   ├── pipeline/
│   │   │   ├── base.py              # PipelineStep protocol, context, progress
│   │   │   ├── runner.py
│   │   │   └── steps/               # one module per step
│   │   ├── sources/
│   │   │   ├── tools.py             # agent-facing tool boundary
│   │   │   ├── arctic_shift/        # the only adapter
│   │   │   └── fake/                # fixture-backed adapter for tests
│   │   ├── analysis/                # prompts, schemas, entity resolution
│   │   ├── ranking/                 # weighting, aggregation, ranking. pure.
│   │   ├── ai/                      # LLMProvider impls (openai, fake)
│   │   ├── persistence/             # SQLAlchemy models, repositories
│   │   ├── jobs/                    # job table, worker loop
│   │   └── api/                     # FastAPI routers, DTOs
│   └── tests/{unit,integration,evaluation}/
└── frontend/
    ├── package.json
    └── src/{app,components,lib}/
```

### 3.2 Running locally — hybrid

Postgres runs in Docker; backend, worker and frontend run natively. Containers give a disposable,
version-correct database and hermetic tests (testcontainers, §9); native processes give hot reload
on the code actually being edited. Rebuilding an image on every keystroke is the cost this avoids.

`docker-compose.yml` uses **profiles**: Postgres is the default service, and everything else sits
behind a `full` profile for whole-stack runs and as the deployment artifact.

Phase 0 must provide these targets, each routing Python through `uv run`:

| Command | Does |
|---|---|
| `make db` | Start Postgres in Docker (detached) |
| `make db-stop` | Stop it |
| `make api` | FastAPI natively, reload on |
| `make worker` | Job worker natively |
| `make web` | Next.js dev server |
| `make test` | Unit + integration (starts its own throwaway Postgres) |
| `make lint` / `make typecheck` | ruff + eslint / mypy + tsc |
| `make stack` | `docker compose --profile full up` — everything containerised |

Day-to-day: `make db` once, then `make api`, `make worker`, `make web` in separate terminals.
Postgres port is configurable via `.env` (default 5432) so a future local install cannot collide.

**Import rule, enforced by a test:** `domain/` and `ranking/` may not import from `sources/`,
`ai/`, `persistence/`, `api/`, or any third-party framework. A test walks the AST and fails the
build on violation. This is how `PROJECT.md` §6.1 stops being an aspiration.

---

## 4. The metric — exact specification

This is the product's headline number. It is defined here once and implemented in exactly one
module (`ranking/aggregation.py`).

### 4.1 Definitions

For a research run `R` with target granularity `G`:

- **Counted opinion** — at most one per `(user, entity)` pair per research, with
  `stance == positive` and `relevance >= relevanceThreshold`. Where a user has several qualifying
  comments about one entity, the **highest-confidence** one is counted and the rest are retained
  as evidence. (`PROJECT.md` §16.)
- **Respondent pool `P`** — the set of distinct users holding at least one counted opinion for
  *any* entity of granularity `G`. **This is the denominator.**
- **Supporters of entity `e`** — distinct users with a counted opinion for `e`.

### 4.2 Formulas

```
supporterCount(e) = |supporters(e)|

share(e)          = supporterCount(e) / |P|

timeWeight(c)     = max(minWeight, 1.0 - decayPerYear * ageYears(c))
                    defaults: decayPerYear = 0.10, minWeight = 0.3

weightedScore(e)  = Σ over u in supporters(e) of
                      max over that user's comments c about e of
                        strength(c) * relevance(c) * timeWeight(c)
```

`weightedScore` weights each *supporter* — never each comment — so it can never exceed
`supporterCount`. This preserves `PROJECT.md` §16's rule that the independent user is the unit.

### 4.3 Ranking

Sort descending by `config.rankingKey` (default `supporterCount`), then by `weightedScore`, then by
`entity.canonicalId` ascending. **The final tiebreak on a stable ID guarantees deterministic output
for identical input** — required by `PROJECT.md` §19 and testable.

### 4.4 Thresholds and presentation

- An entity is a **strong recommendation** at `supporterCount >= minimumIndependentUsers`
  (default 5, per `PROJECT.md` §20).
- Return at most 5 strong recommendations. Return fewer when fewer qualify. **Never pad.**
- Entities below the threshold are persisted and may appear in a separate "weaker signals"
  section, clearly labeled.

**Presentation rules — binding on the frontend:**

- Always show the raw count alongside the percentage.
- Always show the denominator: *"Based on 112 people across 38 discussions."*
- Percentage label is exactly: *"X% of people who answered mentioned this."*
- **Bar charts only. Never a pie chart** — shares can exceed 100% because one person can recommend
  several destinations.

### 4.5 Polling contexts — what qualifies as a vote

Resolves §2.8. Every `SourceDocument` carries a `context_type`:

| Type | Definition | Example | Votes? |
|---|---|---|---|
| `polling` | An open question whose answer set is not pre-determined | *"Most underrated US state for nature?"* | **Yes** |
| `topical` | A leading question, or not a question at all | *"Alaska is underrated, right?"* · *"Just got back from Alaska — photos"* | No |

**Binding rule:** the respondent pool `P` (§4.1) is drawn **only** from comments in polling
contexts. Numerator and denominator come from the same corpus — always. A partial exclusion that
removes an entity's votes while leaving its thread's users in `P` is a defect, and §9's golden
datasets must include a case that would catch it.

**Topical contexts are kept, not discarded.** They are the best available material for two jobs:

1. **Explanations** (Phase 12) — an Alaska-specific thread is the richest source for *why* people
   rate Alaska, and enthusiast reasoning is exactly what that section needs.
2. **Counter-evidence** — dissent inside a topical thread (*"honestly Alaska is overrated, the UP
   beats it"*) is high-signal and is displayed. It is not counted, because it was not solicited by
   a fair question.

**Classification**, cheapest test first:

1. **Deterministic.** Does the title contain a resolved entity alias at the target granularity?
   *"Alaska is underrated"* → names a state → `topical`. Runs against the same alias table as §9's
   entity resolution.
2. **Deterministic.** Does the title have interrogative structure with no named entity?
   *"Most underrated state?"* → `polling`.
3. **LLM classification** for the remainder — this is pipeline step 4, specified in §4.7.

**Budget priority:** polling contexts are retrieved and analysed first. Topical contexts consume
only leftover budget, since they cannot change the ranking. This is also a real cost saving —
a 200-comment vacation photo thread is skipped before a token is spent on it.

**Measure the split.** Phase 15 reports the polling/topical ratio per benchmark query. If polling
contexts prove scarce, this rule starves the corpus and must be revisited — that is a finding, not
a failure.

### 4.6 Pipeline steps — definitive order

Supersedes `PROJECT.md` §12. Three changes: steps 6/7/9 are merged (§2.2), query understanding can
branch to clarification (§6), and **Document Triage is added** as its own step.

| # | Step | AI? | Notes |
|---|---|---|---|
| 1 | Query Understanding | **AI** | → plan · clarification · rejection |
| 2 | Research Planning | no | Budget allocation |
| 3 | Agentic Source Discovery | **AI** | Bounded, via source tools |
| 4 | **Source Document Triage** | **AI** + rules | **New — §4.7. Gates everything downstream** |
| 5 | Content Retrieval | no | Comment trees for surviving documents only |
| 6 | Cheap Pre-filtering | no | Heuristics; embeddings deferred |
| 7 | Comment Analysis | **AI** | Merged relevance + entity + opinion (§5) |
| 8 | Entity Resolution | rules → **AI** | Deterministic first, AI for ambiguity only |
| 9 | User Deduplication | no | One user, one entity, one research |
| 10 | Time Weighting | no | |
| 11 | Aggregation | no | §4.2 |
| 12 | Ranking + Thresholds | no | §4.3, §4.4. **Never AI** (`PROJECT.md` §29) |
| 13 | Result Summarization | **AI** | Grounded in stored evidence only |
| 14 | Persistence | no | |

Five AI steps. Everything that touches the final number is deterministic.

### 4.7 Step 4 — Source Document Triage

Runs on discovery metadata (title, subreddit, comment count, age) **before** any comment tree is
fetched. That placement is deliberate: excluding a thread here avoids both its retrieval cost and
its analysis cost.

**Deterministic pre-checks run first** (`PROJECT.md` §6.4), and short-circuit the AI call:

- `comment_count < minCommentsPerDocument` (default 5) → exclude, no AI call
- title contains a resolved entity alias at the target granularity → `topical`, no AI call
- age beyond `maxDocumentAgeYears` (default 15) → exclude

**AI classification** handles the remainder, batched (~120 titles in one or two calls):

```python
class DocumentTriage(BaseModel):
    document_id: str
    verdict: Verdict            # polling | topical | exclude
    scope_match: bool           # inside the query's geographic scope
    granularity_match: bool     # answers the target entity tier
    criterion_match: bool       # reflects the query's criteria e.g. "underrated"
    confidence: float
    reason: str                 # one sentence — persisted, and read during evaluation
```

`verdict == polling` requires `scope_match and granularity_match`. A thread failing
`criterion_match` is downgraded to `topical` rather than excluded: it still holds real opinions,
they just do not answer *this* question.

**Erring direction.** Below `triageConfidenceThreshold` (default 0.6) a document is downgraded to
`topical`, never promoted to `polling`. Excluding a good thread costs evidence; admitting a biased
one corrupts the ranking, and only the second is invisible to the user. Configurable, and the
consequences are measured in Phase 15.

**This step is a single point of failure for the whole corpus.** A classifier that is too strict
starves every query at once, and it would look exactly like "Reddit has nothing to say." Mitigations
are mandatory, not optional:

1. Every verdict is persisted **with its reason**, so a thin result is always explainable.
2. Statistics record the triage breakdown — how many documents were polling, topical, excluded, and
   why — and the API exposes it.
3. If the polling share falls below `minPollingDocumentRatio` (default 0.15), the research is
   flagged and the triage breakdown surfaces in the response. Persistent flagging is a signal the
   threshold is wrong, not that Reddit is quiet.

---

## 5. Comment analysis contract

One structured LLM call per batch of comments (default 20), replacing `PROJECT.md` §12 steps 6, 7
and 9. Response is validated by Pydantic; invalid items are dropped with a logged reason, never
coerced.

```python
class EntityMention(BaseModel):
    raw_text: str                  # verbatim from the comment
    normalized_guess: str
    entity_type: EntityType        # country|region|state|city|town|park|beach|trail|island|other
    stance: Stance                 # positive|negative|mixed|mention_only
    strength: float                # 0.0-1.0, enthusiasm of the recommendation
    supporting_quote: str          # verbatim span. MUST appear in the comment.

class CommentAnalysis(BaseModel):
    comment_id: str
    topic_relevance: float         # 0.0-1.0  matches the query topic
    criterion_relevance: float     # 0.0-1.0  matches criteria e.g. "underrated"
    scope_match: bool              # inside the query's geographic scope
    overall_confidence: float      # 0.0-1.0
    mentions: list[EntityMention]
    reasoning: str                 # one sentence, for debugging
```

**Anti-fabrication rule (`PROJECT.md` §29 "never silently invent evidence"):** every
`supporting_quote` is verified by exact substring match against the stored comment body. A mention
whose quote is not found is **discarded and counted in a `fabricated_quote` metric**. This is a
deterministic check, not a prompt instruction, and it is tested.

---

## 6. Query understanding and the clarification loop

Resolves §2.4. Query Understanding returns one of two outcomes:

```python
class ResearchPlan(BaseModel):
    normalized_query: str
    scope: GeoScope                    # e.g. {type: "country", value: "United States"}
    entity_granularity: EntityType     # the target tier — states, towns, parks...
    granularity_confidence: float
    topic: str                         # "nature"
    criteria: list[str]                # ["underrated"]
    seed_queries: list[str]            # bounded by maxSearchQueries
    candidate_subreddits: list[str]

class ClarificationRequest(BaseModel):
    question: str
    options: list[ClarificationOption]  # each maps to an entity_granularity
    allow_grouped: bool                 # "show all tiers, grouped" is always offered
```

When `granularity_confidence < config.granularityThreshold` (default 0.7), the research
transitions to **`needs_clarification`** and stops. The frontend renders the question; the user's
answer is POSTed back; the research resumes from the plan.

Example — *"Most underrated US destinations for nature"*:

> **What kind of places are you looking for?**
> · States and regions · National parks and natural areas · Towns and small cities
> · Show all of these, grouped separately

Choosing "grouped" produces one ranked list per tier, each with its own respondent pool `P`
(a state-answerer and a town-answerer are different denominators — mixing them would be wrong).

**Non-travel queries:** if the query is not a travel-recommendation question, Query Understanding
returns a rejection and the research completes with status `rejected` and an explanation. It does
not consume budget.

**Language:** English-only for MVP. Non-English comments are dropped at pre-filter and counted in
statistics.

---

## 7. Research lifecycle

```
pending
  │
  ├─ source preflight fails ─────────────────────> source_unavailable  (terminal, no cost)
  │
  v
understanding ──┬──> rejected            (not a travel question)
                ├──> needs_clarification ──> (user answers) ──┐
                └──────────────────────────────────────────────┤
                                                               v
                                                          discovering
                                                               │
                     retrieving ──> analyzing ──> aggregating ──> completed
                                                               │
                                                               ├──> completed_partial
                                                               │    (budget/time hit, source healthy)
                                                               │
                                                               └──> completed_degraded
                                                                    (source health below floor)

any state ──> failed             (unexpected error, recorded)
any state ──> source_unavailable (all adapters failed)
any state ──> cancelled          (user)
```

### 7.1 Terminal states, and what each one promises

| Status | Means | Results page? |
|---|---|---|
| `completed` | Ran fully, source healthy | Yes — normal |
| `completed_partial` | Hit a budget or time limit, **source healthy**. Evidence is real but incomplete | Yes — with the limiting factor named |
| `completed_degraded` | Source health below floor. Numbers are **not trustworthy as a sample** | Yes — but banner-flagged, ranking de-emphasised |
| `source_unavailable` | Every adapter failed. There is no evidence at all | **No.** Error state only |
| `rejected` | Not a travel-recommendation question | No |
| `failed` | Unexpected internal error | No |
| `cancelled` | User cancelled | No |

The distinction between `completed_partial` and `completed_degraded` is the whole point. The first
says *"we stopped early on purpose"* — `PROJECT.md` §21's graceful stop, and the evidence gathered
is a valid sample. The second says *"we could not see properly"* — the evidence may be arbitrarily
biased by which requests happened to succeed, and no honest percentage can be computed from it.

**Binding rule:** a thin result set may be reported as a genuine finding **only** when source health
passed. Otherwise the shortfall is attributed to the source, never to Reddit's opinions.

---

## 8. Source access — Arctic Shift

Base URL `https://arctic-shift.photon-reddit.com`. No authentication.

| Endpoint | Use |
|---|---|
| `/api/comments/search` | **Primary discovery.** Full-text search over comment bodies |
| `/api/posts/search` | Thread-level discovery |
| `/api/comments/tree` | Full comment tree for a post (up to 25k) |
| `/api/subreddits/search` | Find relevant communities |

Comment-body search is the key capability — it searches the actual unit of evidence directly.

**Adapter responsibilities** (`PROJECT.md` §11): retries with exponential backoff, 429 handling,
pagination, response validation, normalization to domain types, deleted/`[deleted]` author
handling, timestamp and permalink capture.

**Operational reality:** free service, no uptime guarantee, ~36h data lag. The lag is irrelevant —
this product aggregates opinions expressed over years. The uptime risk is mitigated by (a) the
`SourceAdapter` port, (b) an HTTP response cache so development and re-runs do not re-hit the
service, and (c) the recorded-cassette test suite, which never touches the network.

**Politeness:** default 2 req/s ceiling, configurable, with a descriptive `User-Agent`. Bulk
backfill must use the monthly dumps, not the API.

**Bot filtering:** drop `AutoModerator`, any author matching `*-bot` / `*_bot`, and a configurable
denylist, before analysis.

### 8.1 Failure semantics — when the source is down

Arctic Shift is currently the only adapter, so "all adapters failed" and "Arctic Shift is down" are
the same event today. The logic is written for **N adapters** so adding sources later changes only
the count, not the rules.

**Preflight.** Before any budget or token is spent, the pipeline health-checks every registered
adapter. If **none** is reachable, the research terminates immediately as `source_unavailable` at
zero cost. Discovering the outage after paying for query understanding is a waste and delays the
error the user needs to see.

**Health accounting.** The runner records per adapter, and persists into the snapshot (`PROJECT.md`
§23 requires enough metadata to understand a result):

```python
class SourceHealth(BaseModel):
    adapter: str
    calls_attempted: int
    calls_succeeded: int
    calls_failed: int
    failure_kinds: dict[str, int]   # timeout | rate_limited | http_5xx | malformed | ...
    success_rate: float
```

**Outcome rules,** evaluated after retrieval:

1. **Every adapter failed every call** → `source_unavailable`. No results. No results page. The API
   returns a machine-readable error naming the adapters and their failure kinds.
2. **Aggregate `success_rate < minSourceSuccessRate`**, or `posts_retrieved < minPostsRetrieved`, or
   `comments_analyzed < minCommentsAnalyzed` → `completed_degraded`. Results are computed and
   stored, but the API marks them untrusted and the UI must banner them. **Percentages are
   suppressed** — the denominator is not a meaningful sample, so only raw counts are shown.
3. **Health passed but evidence is genuinely thin** → `completed`, fewer than five results, and
   `PROJECT.md` §20's honest message. This is the *only* path that may say "we found 2 strong
   recommendations."
4. **With several adapters, some up and some down** → continue on the survivors, record which
   sources contributed, and apply rule 2 against the aggregate. A result built from one of three
   intended sources is degraded even if that one source was perfectly healthy.

**Retry before conceding.** Transient failures are retried with exponential backoff inside the
adapter (`PROJECT.md` §11) and count as failures only after retries are exhausted. A single 429 is
not an outage.

**Never substitute.** When the source is unavailable the system does not fall back to cached data
from a different research, does not fill gaps from the LLM's own knowledge, and does not soften the
error into an empty result. `PROJECT.md` §29: never fabricate source data.

---

## 9. Testing strategy

Follows `PROJECT.md` §26. Concretely:

| Layer | Tool | Rule |
|---|---|---|
| Unit | pytest | No network. No LLM. Fast. |
| Integration | pytest + testcontainers | Real Postgres, faked source and LLM |
| Cassettes | recorded JSON fixtures | Real Arctic Shift responses, committed, replayed offline |
| Evaluation | pytest, `-m evaluation` | Real LLM calls. **Excluded from CI.** Run manually |
| Frontend | Vitest + Playwright | Component + one E2E happy path |

**`FakeLLMProvider`** returns fixture responses keyed by prompt hash — deterministic, offline, and
able to simulate malformed output, refusals, and timeouts. It is the **default provider** —
`LLM_PROVIDER` must be set explicitly to reach OpenAI (§10 Phase 7.5), so no test run can bill an
account by accident.

**Golden datasets** for `ranking/`: small hand-calculated fixtures where the expected supporter
counts, shares, and order are known exactly and asserted to the decimal. `PROJECT.md` §27 Phase 11
requires this; it is the single most valuable test suite in the project because it protects the
number the user actually reads.

**Architecture test:** the import-boundary check from §3.1 runs in CI.

---

## 10. Phase plan

Each phase ends with a report (§12) and a stop. Phases 0–3.5 require no network and no LLM.

| # | Phase | Depends on | Ships |
|---|---|---|---|
| 0 | Foundation | — | Repo, Compose (Postgres + `full` profile), Makefile, CI, lint/type/test green on an empty project |
| 1 | Domain contracts | 0 | Pydantic domain models, `SourceAdapter` + `LLMProvider` protocols, budget config, import-boundary test |
| 2 | Fake pipeline | 1 | Step protocol, runner, progress, fake source + fake LLM, full fake run query→result |
| 3 | Persistence | 2 | Postgres schema, Alembic, repositories, job table, worker loop |
| **3.5** | **Walking skeleton** | 3 | **Thin API + minimal UI on the fake pipeline. First demoable product.** |
| 4 | Arctic Shift adapter | 1 | Real adapter + cassettes, retries, **preflight health check** |
| 5 | Query understanding | 1 | Plan extraction, granularity detection, **clarification loop**, rejection path |
| 6 | Agentic discovery | 4, 5 | Source tool boundary, bounded agent loop, duplicate-query prevention |
| 7 | **Triage** + retrieval + pre-filter | 4, 6 | **§4.7 Document Triage step**, bounded retrieval, dedup, heuristic pre-filter, budget enforcement, **§8.1 health accounting** |
| **7.5** | **Real LLM provider** | 5 | **OpenAI adapter behind the port, runtime settings + `OPENAI_API_KEY`, provider selection defaulting to fake** |
| 8 | Comment analysis | 5, 7 | The merged §5 call, quote verification, labeled fixture set |
| 9 | Entity resolution | 8 | Deterministic normalization → alias table → AI only for ambiguity |
| 10 | Opinion + dedup | 9 | Signed stance, one-user-one-entity rule, evidence retention |
| 11 | Aggregation + ranking | 10 | §4 math, golden datasets, thresholds, partial results |
| 12 | AI summaries | 11 | Evidence-grounded explanations, traceable to stored quotes |
| 13 | API hardening | 3.5, 12 | Full endpoints, cancellation, error contract, OpenAPI, **composition root switched to the real pipeline** |
| 14 | Frontend | 13 | Search, clarification, progress, results, evidence drill-down, empty states |
| 15 | Evaluation | 14 | Benchmark queries, precision measurement, cost/latency, weakest-stage analysis |

### Notable phase details

**Phase 0 — acceptance:** `make db` starts Postgres in Docker and it accepts connections;
`docker compose --profile full up` starts every service; `make test`, `make lint`, `make typecheck`
all pass with zero business logic present. CI runs all three. See §3.2 for the required commands.

**Phase 1 — acceptance:** every domain object round-trips through serialization; invalid data is
rejected with a useful error; the import-boundary test passes. No network, no DB.

**Phase 2 — acceptance:** a complete fake research runs query → ranked result with zero external
calls, in under a second.

**Phase 3 — acceptance:** two identical searches produce two distinct persisted records
(`PROJECT.md` §27 Phase 3). A worker crash mid-run leaves recoverable state.

**Phase 3.5 — acceptance:** you can type a query in a browser, watch progress, and see a fake
ranked result. `POST /research`, `GET /research/{id}`, polling, results page. Deliberately ugly.

**Phase 4 — acceptance:** cassettes cover success, 429, malformed JSON, deleted authors, empty
results, and pagination. Tests never touch the network. The preflight health check correctly reports
a reachable and an unreachable source.

**Phase 5 — acceptance:** an ambiguous query produces a `ClarificationRequest`; a specific query
produces a plan directly; a non-travel query is rejected without consuming budget.

**Phase 6 — acceptance:** the agent conducts a bounded multi-search discovery through the tool
boundary. Tests prove it cannot exceed `maxSearchQueries`, cannot repeat near-duplicate queries,
never sees credentials, and handles tool failure. Fake tools throughout (`PROJECT.md` §26).

**Phase 7 — acceptance:** §8.1's four outcome rules are each covered by a test. Specifically: a
total source outage yields `source_unavailable` with **no results object at all**; a 50% failure
rate yields `completed_degraded` with percentages suppressed; a healthy run returning little data
yields `completed` with an honest thin result. **A test asserts that a degraded run can never
produce the same user-facing message as a genuinely thin one** — this is the regression that would
otherwise reintroduce §2.7.

**Phase 7 — triage acceptance:** deterministic pre-checks short-circuit before any AI call; leading
titles naming an entity classify as `topical`; open questions classify as `polling`; scope,
granularity and criterion mismatches are each caught by a fixture. Low-confidence documents downgrade
to `topical` and are never promoted to `polling`. Triage verdicts and reasons are persisted and
exposed. A test asserts that excluding a topical thread removes its users from **both** the numerator
and the respondent pool. **Triage runs before retrieval** — a test asserts no comment tree is fetched
for an excluded document.

**Phase 7.5 — acceptance:** the OpenAI adapter satisfies `LLMProvider` and is exercised against a
stubbed client with **no network in the normal suite**; model IDs, timeouts, retries and token caps
live in an `OpenAIConfig` following the `ArcticShiftConfig` pattern, never in `domain/`. Settings
read `OPENAI_API_KEY` from the environment; `.env.example` documents it and the key is never logged
or persisted. `LLM_PROVIDER` selects fake or openai and **defaults to fake**, so `make test` and CI
stay offline. Two §0.1 tests: a missing or rejected credential fails the research with an explicit
provider-failure reason and **no results object**, and it is distinguishable from a genuinely thin
run. The import-boundary test still passes.

**Phase 8 — acceptance:** a labeled fixture set covering clearly relevant, indirectly relevant,
irrelevant, ambiguous, and differently-worded-but-equivalent comments. Semantic matches succeed
where keyword matching would fail. Quote verification rejects fabricated spans.

**Phase 11 — acceptance:** golden datasets produce exactly the expected counts, shares, and
ordering, **including a fixture where a topical thread's users must not appear in `P`**. Identical input yields byte-identical output across runs. **No LLM is involved in
ordering** (`PROJECT.md` §29).

**Phase 15 — benchmarks:** underrated US states for nature; US national parks avoiding crowds;
underrated European road-trip regions; best regions for cycling and nature. For each: inspect a
sample of retrieved comments by hand, measure relevance precision, check entity resolution and
deduplication, compare ranking against manually reviewed evidence, record cost and latency.
**Identify the weakest stage before optimizing anything** (`PROJECT.md` §27).

---

## 11. API surface

```
POST   /api/research                    -> {id, status}
GET    /api/research/{id}               -> status, progress, statistics, budget used
POST   /api/research/{id}/clarify       -> answer a ClarificationRequest, resume
GET    /api/research/{id}/results       -> ranked results (grouped by tier when applicable)
GET    /api/research/{id}/evidence      -> evidence for an entity, paginated
POST   /api/research/{id}/cancel        -> cancel a running research
```

Frontend polls `GET /research/{id}` every 2s while running. The API exposes **domain concepts
only** — no Arctic Shift or Reddit structures leak through (`PROJECT.md` §25).

Every result item carries: entity name and type, supporter count, share, denominator, discussion
count, weighted score, confidence, explanation, and evidence links to source permalinks.

---

## 12. Definition of Done

Per `PROJECT.md` §28. A phase is complete only when implementation exists, automated tests exist
and pass, lint and type checks pass, failure cases are covered, it integrates with prior phases,
and acceptance criteria are demonstrably met.

Report format, then **stop**:

```
Phase:
Implemented:

Tests:
- ...

Validation:
- tests:     PASS (n passed)
- lint:      PASS
- typecheck: PASS

Acceptance criteria:
- <criterion>: PASS

Known limitations:
- ...
```

---

## 13. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Arctic Shift goes down or changes terms | **High** — sole data source | `SourceAdapter` port; response cache; cassettes keep dev and tests working; official Reddit adapter is a known fallback. **§8.1 guarantees an outage surfaces as a loud error, never as a thin result** |
| LLM extracts entities inconsistently | High — corrupts ranking | Deterministic normalization first; alias table; AI only for ambiguity; never merge below confidence (`PROJECT.md` §15) |
| Reddit's loudest answers dominate ("Alaska effect") | Medium — output is obvious, not useful | Largely the *correct* answer to "what do people say". Surface discussion counts (§4.4) so users judge concentration themselves; consider a novelty signal post-MVP |
| §4.5 starves the corpus if polling contexts are rare | Medium — thin evidence everywhere | Phase 15 measures the polling/topical split per query; relax the classifier if it over-excludes |
| §4.7 triage is too strict and silently starves every query | **High** — indistinguishable from "Reddit is quiet" | Verdicts + reasons persisted; triage breakdown exposed in the API; research flagged below `minPollingDocumentRatio` |
| Sparse evidence on niche queries | Medium | Threshold and partial results already handle it; show fewer results and say so |
| One person on several accounts | Low | Undetectable. Document as a known limitation |
| Prompt injection from comment text | Medium | Comments are data, never instructions. Structured output + quote verification bound the blast radius |
| Model output drifts as OpenAI updates models | Medium | Pin model IDs in config; evaluation suite detects regressions |

---

## 14. First task

**Phase 0 — Project Foundation.**

Create the repository skeleton, Docker Compose, backend and frontend scaffolds, CI, and the
lint/type/test toolchain. No business logic.

Acceptance: `docker compose up` runs; `make test`, `make lint`, `make typecheck` pass; CI executes
all three; no domain code exists yet.

Then stop and report.
