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
| Default model | **`gpt-5.6-luna`** (see §2.10). Larger tier for query understanding + summaries remains intended | Cost-oriented reasoning tier; per-research cost to be measured in Phase 15 |
| Model config | Model IDs in config only. **Never in the domain layer** | `PROJECT.md` §13 |
| Source | **Arctic Shift for retrieval** (`https://arctic-shift.photon-reddit.com`); **a web search provider for discovery** (see §2.11) | No API key or approval needed for Arctic Shift. Its keyword search is measurably unreliable; its ID-based retrieval is not |
| Search provider | **Serper.dev** (Google results), behind a `WebSearchProvider` port, **defaulting to `fake`** | Google indexes Reddit threads better than any free Reddit search. Port keeps it replaceable (§2.11) |
| Source port | `SourceAdapter` and `WebSearchProvider` ports are both built | Two external services, two ports; `WebSearchProvider` has two real implementations |
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
maxResearchDuration   300s   # whole research. Enforced from Phase 14.6 (§2.12.2) by refusing
                             # to admit new work; in-flight calls always finish
tailReserve            60s   # subtracted from it to derive the dispatch deadline
maxEstimatedCostUSD  0.50    # hard stop
```

`maxAIAnalysisItems` is a ceiling on the *total*, never a licence to spend it on the first few
documents: from Phase 14.6 the budget is distributed across every surviving document (§2.12), so
breadth of discussions is a property of the sample, not an accident of ordering.

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

- **Additional source adapters** (official Reddit API, travel forums, YouTube) —
  deferred as *future work*, not rejected. `PROJECT.md` §3 makes multi-source the roadmap, and the
  `SourceAdapter` port exists to serve it. The MVP ships one source adapter because one is enough
  to validate the product, not because the port is speculative. (Web search is no longer on this
  list: §2.11 makes it the discovery mechanism, not a second source of evidence — it supplies
  thread *addresses*, never content that reaches the corpus.) Adding the next source must not
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

### 2.10 The default model is now `gpt-5.6-luna` — **§1 amended**

§1 locked `gpt-5-mini` as the default analysis model, chosen for the ~$0.15/research figure in
§1.1. **User decision during Phase 7.5:** the default is now `gpt-5.6-luna`, OpenAI's
cost-oriented reasoning tier (released 2026-07-09), which the Responses API serves with strict
structured outputs — the guarantee every AI step in this system depends on.

Two consequences the plan should not pretend away:

1. **§1.1's ~$0.15/research is no longer a verified figure.** It was derived for a different
   model. It stays as the *target*, and Phase 15 measures the real number, as it was always going
   to.
2. **`reasoning.effort` is now a live cost lever** (`none | low | medium | high | xhigh | max`,
   default `medium`) that `OpenAIConfig` does not yet expose, because no step calls the provider
   yet. The phase that first does should add it rather than accept the default silently.

The model id is config (`OpenAIConfig.model`), never a constant in the domain layer, so this
amendment changes one default and nothing else.

---

### 2.11 Discovery moves to web search — **§1, §4.6, §8, §8.1 amended; Phase 14.5 added**

§8 calls Arctic Shift's full-text search "the key capability" and §4.6 step 3 is built on it.
Measured against the live service during Phase 14 manual testing, that one capability does not
work well enough to build a product on. The other endpoints do.

**The measurement** (live `curl`, same machine, interleaved, two different egress IPs):

| Endpoint | Successes | Latency |
|---|---|---|
| `/api/posts/search` (keyword) | **1 / 5** | 5.5–11 s, then timeout |
| `/api/posts/ids` | 6 / 6 | 0.2–1.0 s |
| `/api/comments/search?link_id=…` | 6 / 6 | 0.2–1.0 s |

This is not rate limiting and not our request volume — changing egress IP changed nothing, and the
ID-based calls stayed instant throughout the same window. Arctic Shift's own API documentation
says as much: keyword parameters (`title`, `selftext`, `query`, `body`) are *"only in use with
author or subreddit parameter (not supported with very active users or subreddits)"*, and its
timeout guidance tells callers to *"use a more specific filter… this usually happens with body,
selftext or title parameters."* The service is honest about which half of it is load-bearing.

So: **Arctic Shift is not the wrong source. Its search is the wrong index.** Retrieval — the part
we actually depend on for evidence — is excellent.

**Resolution: discovery finds threads through a web search provider; Arctic Shift hydrates them.**

```
LLM proposes a natural-language query
  → WebSearchProvider.search(query)        # Google results, Reddit threads
  → extract post ids from the result URLs
  → SourceAdapter.fetch_documents(ids)     # /api/posts/ids, ≤500 per call
  → Triage → Retrieval → Analysis → …      # unchanged
```

Three reasons this is an upgrade rather than a workaround:

1. **It is the reliable path.** Both remaining external calls are the ones measured at 6/6.
2. **It ranks by relevance, not recency.** The current step sends `sort=desc` and takes the newest
   matching threads. A search engine returns the threads people actually found useful. For a
   product whose whole premise is aggregating what people said, that is a better corpus.
3. **It removes the subreddit-scoping constraint** that §4.6 step 3 currently has to work around
   by discarding LLM turns that propose no subreddit.

**Provider choice, and why it is behind a port.** The first implementation is **Serper.dev**
(real Google results, 2,500 free queries, no card required). Google's own Custom Search JSON API
is closed to new customers, and PullPush refuses automated clients outright, so the field is
narrow — which is exactly the argument for the port. `WebSearchProvider` is a protocol in
`domain/ports.py` with two implementations from day one, `fake` and `serper`, selected by
`SEARCH_PROVIDER` and **defaulting to `fake`**, mirroring §9's `LLM_PROVIDER` rule so no test run
and no accidental start-up can spend a quota.

**One measured provider constraint.** On a free Serper account, `site:reddit.com` with `num=10`
succeeds and the identical query with `num=25` is rejected — `HTTP 400 "Query pattern not allowed
for free accounts"`, a message that blames the operator but is really about the combination. Since
every discovery query carries that operator, an unclamped request would fail *every* search and
land the research on `source_unavailable`. The ceiling therefore lives in `SerperConfig`
(`max_results_per_query`, default 10) and the provider clamps to it: a provider's own limits belong
to the provider, not to §1.1's budget. Ten is Google's first page anyway, and `maxSearchQueries 12`
× 10 still reaches `maxTotalPosts 120`.

**Sections amended:**

- **§1 — "Source"** now reads: *Arctic Shift for retrieval; a web search provider for discovery.*
  **"Source port"** is no longer "only one adapter implements it": there are now two ports over
  two external services, and `WebSearchProvider` genuinely has two implementations.
- **§3.1** gains `search/` (`fake/`, `serper/`), a sibling of `ai/` and for the same reason.
- **§4.6 step 3** — "Agentic Source Discovery" keeps its budget, its duplicate-query prevention and
  its unproductive-turn abort. What changes is what a turn issues: a natural-language search query
  with no required subreddit, and a hydrate call after the loop.
- **§8** — `/api/comments/search` is no longer "Primary discovery" (it never was, in code: the
  adapter only ever used `/api/posts/search`). The table becomes: `posts/ids` for hydration,
  `comments/search?link_id` for comment trees. `posts/search` is dropped.
- **§8.1** — health accounting now covers **two** external dependencies. It was already written
  "for N adapters", so the rules do not change; `search` is recorded as its own named entry, and a
  run whose search provider failed every call is `source_unavailable` by rule 1 exactly as a dead
  Arctic Shift would be. The §0.1 obligation is unchanged and now has two ways to be breached:
  *a run that found nothing because search was down must never be described like a run that
  searched properly and found little.*
- **§9** — `FakeSearchProvider` joins `FakeLLMProvider` under the same rule: fixture-backed,
  offline, the default, and able to simulate failure. No test touches Serper.
- **§10** — new **Phase 14.5**, placed *before* Phase 15 so evaluation measures the fixed
  pipeline rather than the broken one.

**Phase 14.5 — Search-backed discovery** · depends on 6, 14 · ships: `WebSearchProvider` port,
`FakeSearchProvider`, Serper adapter, `SEARCH_PROVIDER` + `SERPER_API_KEY` settings, Reddit-URL →
post-id extraction, `SourceAdapter.fetch_documents` batch hydration, discovery step rewritten onto
search, §8.1 accounting extended to both dependencies.

**Acceptance:** a full run reaches ranked results using `SEARCH_PROVIDER=fake` with **no network at
all**; a search provider that fails every call yields `source_unavailable` with no results object,
not an empty finding; a URL that is not a Reddit post is discarded without a hydrate call; the
hydrate path batches ≤500 ids per request; the discovery loop still cannot exceed
`maxSearchQueries` or repeat a near-duplicate query.

---

### 2.12 The pipeline is unusably slow and samples too narrowly — **Phase 14.6 added**

The first full real run after §2.11 completed as `completed_partial` in **2408 s** against §1.1's
`maxResearchDuration` of 300 s and its stated target of "~2–4 minutes". The run before it died at
1487 s on a single OpenAI connection error, losing 24 minutes of finished work. Neither is a tuning
question; both are defects, and both were invisible because nothing reads the duration budget.

**Where the time goes,** measured over the full run (66 LLM calls):

| Step | Calls | Time |
|---|---|---|
| Comment analysis | 50 | **2245.9 s (93 %)** |
| Everything else combined | 16 | 106.3 s |

Comment analysis runs its batches **strictly sequentially** (`comment_analysis.py`,
`for batch in _batched(...): await self._analyse(...)`), so 1000 comments ÷ 20 = 50 round trips
in series.

**What makes one call slow.** Measured on one real 20-comment batch: input 1782 tokens, output
2470. Latency tracks output, and the output is mostly not the answer:

| Response field | Share of JSON payload |
|---|---|
| `reasoning` (one prose sentence per comment, never shown to a user) | **50.2 %** |
| `mentions.supporting_quote` (the §5 anti-fabrication evidence) | 20.6 % |
| `mentions.raw_text` | 5.1 % |
| `mentions.normalized_guess` (Phase 9 recomputes it anyway) | 5.0 % |
| every numeric/enum field together | ~12 % |

`reasoning.effort` is a smaller lever than it looks: default 32.7 s, `low` 23.2 s, `none` 20.7 s,
with 20/20 comments analysed at every level. §2.10 already said the first phase to call the
provider should set it deliberately; Phase 8 did not.

**The sampling defect is separate, and worse.** `prefilter.py` fills the analysis budget with
`_truncate(counted, max_items)` — the *first* N comments in document order. In the measured run
that meant **3 of 81 surviving threads** supplied every counted opinion (566 + 424 + 10 comments);
threads 4–81 contributed nothing, and no `topical` thread was retrieved at all. Raising the budget
does not fix this: it would buy the first 15 threads instead of the first 3.

This matters beyond volume. Each thread is a *different population* — r/AskAnAmerican, r/hiking and
r/mountainbiking are not the same people answering. Sampling three threads samples three
communities. It also silently caps `discussion_count`, which §4.2 uses to signal corroboration
across independent discussions: the measured top result's "3 threads" was the ceiling, not a
finding.

**Resolution:** insert **Phase 14.6**, before Phase 15, covering six changes — shrink the analysis
response, run batches concurrently, isolate batch failure, sample every thread, enforce the
duration budget, and make quote verification tolerant of formatting while keeping it deterministic.

Phase 15 stays the phase that *tunes* (budget size, triage thresholds, effort level). 14.6 only
makes the instrument usable and honest; the test for what belongs here is **"does it change a
number the user reads?"** — if yes, it waits for measurement.

#### 2.12.1 Quote verification stays deterministic — the rule is relaxed, not removed

§5's anti-fabrication rule discards any mention whose `supporting_quote` is not an exact substring
of the comment. Nine discarded mentions from the measured run were inspected by hand against their
source comments:

* **six** genuinely contained the named place and failed only on formatting — a doubled space, a
  parenthesis (`Hot Springs (National Park)`), capitalisation;
* **three did not**, and those are the reason the rule exists:
  * a comment praising *"the shore of Lake **Huron**"* produced a mention of **Lake Michigan** —
    a real person's real opinion, attached to the wrong place, in the run whose top result was
    Michigan;
  * a comment about Michigan mosquitoes and South Haven produced a mention of **Detroit**, a city
    it never names — inference presented as testimony.

Neither is an invented *place*; both are invented *attributions*, and both are invisible after the
fact because the number, the source and the person are all real. Extrapolated from this sample,
roughly two thirds of the run's 43 discards (1.5 % of 2915 mentions) were recoverable formatting
misses and one third were genuine misattributions.

**So:** normalise both sides (case, whitespace runs, typographic quotes and dashes), then accept a
fuzzy match at **≥ 0.90 similarity**; below that, discard. The check stays deterministic and the
quote stays findable in the original comment by a human — which an LLM self-assessment could not
promise, since the model that wrote `Lake Michigan` wrote it confidently.

**Audit trail (required, not optional).** Every verification that is not an exact match — accepted
*and* rejected — records the claimed quote, the best-matching span, the similarity score and the
verdict. Without it the 0.90 threshold is a guess nobody can revisit: the two questions worth
asking later are "what was admitted just above the line that should not have been" and "what was
dropped just below it that should have stayed", and both need the borderline cases kept. Phase 15
calibrates the threshold from this record.

#### 2.12.2 The duration limit stops admission, never completion

A deadline that cancels work in flight throws away tokens that are already paid for and gets
nothing back for them — the request was billed the moment it was sent, so abandoning the response
buys no saving, only a smaller sample. The limit therefore gates **what may still be started**, not
what may finish.

Three rules, in order of precedence:

1. **No new expensive work is admitted after the deadline.** In comment analysis this is the
   dispatch loop: once the deadline passes, no further batch is sent.
2. **Everything already in flight is awaited and its result is kept.** Because batches run
   concurrently (14.6b) the overrun this can cause is bounded by *one* batch — the per-call timeout,
   not the sum of the outstanding ones.
3. **Point of no return: the first successful analysis batch.** After it, every remaining step runs
   to completion regardless of the clock. Steps 8–14 are entity resolution, deduplication, time
   weighting, aggregation, ranking, summarization and persistence; measured against analysis they
   are almost free, and stopping there would mean paying for the whole corpus and delivering
   nothing. A run that has evidence always turns it into a result.

**So the 300 s is a promise about the whole research, and the dispatch deadline is derived from it,
not equal to it:** `admission_deadline = started_at + maxResearchDuration − tailReserve`, with
`tailReserve` in config. Stating it the other way round — deadline at 300 s, then a tail on top —
would make the user's five minutes mean seven, which is the kind of quiet redefinition §0.1 exists
to prevent.

**Floor.** The analysis step always dispatches at least one concurrent wave, even if the deadline
has already passed when it starts. A run that spent query understanding, triage and retrieval and
then analysed nothing is the worst possible outcome: full cost, zero evidence, and a result page
that cannot say anything. One wave is one batch-latency long.

**Accounting (§8.1, §0.1).** Comments that were never dispatched are **budget-limited**, not
**failed**, and the two are counted separately — `comments_not_analysed_budget` against
`comments_lost_to_errors`. They mean different things to a reader: the first says "we stopped on
purpose and this sample is valid but smaller", the second says "we tried and could not see". §7.1
already separates these as `completed_partial` and `completed_degraded`; the counters are what let
the runner tell them apart.

#### 2.12.3 What the verification run measured

One real run after 14.6a-f, same query as the 2408 s measurement
(*"Most underrated US states for nature"*), real Serper and real OpenAI.

| | before (§2.12) | after |
|---|---|---|
| Whole run | 2408 s | **282.5 s**, `completed_partial` |
| Comment analysis | 2245.9 s / 50 calls | **147.1 s / 42 calls** |
| Threads contributing counted opinions | 3 of 81 | **12-13 of 13** |
| Top result's `discussion_count` | 3 (the ceiling) | **12** |
| Mentions discarded for an unusable quote | 43 / 2915 = 1.5 % | **2 / 2121 = 0.09 %** |

**The two runs did not see the same corpus** — 81 threads survived triage then, 20 now — because
discovery is agentic and not deterministic. Structural numbers are comparable; the result *list*
is not.

**What worked.** 42 analysis calls totalling 1077.8 s of call time finished in 147.1 s of wall
clock: a 7.3x compression against a ceiling of 8. The admission deadline fired exactly as §2.12.2
describes — 8 batches refused, 160 comments recorded as budget-limited, none lost to errors, and
the run landed at `completed_partial` naming its limiting factor. The in-flight tail ran 24.9 s
past the deadline and the whole run used 42.5 s of the 60 s `tailReserve`. `reason_code` needed no
`OTHER` in 840 comments, so the closed set covers a real corpus.

**What did not.** Shrinking the analysis response bought no measurable latency (see §5). 14.6a
stands on countability.

**Three findings this run produced, none of them inside 14.6's scope:**

1. **Retrieval is now the breadth ceiling.** 18 documents survived triage as `polling`; **13 were
   retrieved**, because `maxComments` fills in *document order* — the same defect §2.12 found in
   pre-filter, one step earlier. `documents_retrieved` against `documents_polling` makes it
   visible, so it is not a §0.1 violation, but the sample is still lopsided.
2. **Discovery is the second-largest cost** at 56.6 s (20 %), fully sequential: 11 model calls and
   10 searches, none overlapping.
3. **61 % of extracted mentions are off-granularity** (1284 of 2121) — paid-for output a
   state-tier question cannot use.

The quote audit trail earned its place immediately. Both rejections were the failure §2.12.1
describes — one claimed *"Vermont ... is so incredibly beautiful in fall"* where the comment said
*"new england is so incredibly beautiful in fall"* — and the accepted near-misses were almost all
**markdown markup** (`*western* virginia`, `[nature reserve]`), which suggests a cheap
deterministic fold Phase 15 can now justify from data rather than guess at.

---

### 2.13 A run reports once, after five minutes of silence — **Phase 14.7 added**

The verification run in §2.12.3 finished in 282.5 s and reported **once**, at the end. Everything
before that is a status line and a spinner. This is not the speed defect §2.12 fixed — a sixty-second
run would still report once, at the end — it is the reporting model: nothing downstream of analysis
runs until analysis is finished, so nothing can be shown until analysis is finished.

The lever is that steps 8-11 — entity resolution, deduplication, aggregation, ranking — are cheap and
almost entirely deterministic. Re-running them over the comments analysed *so far*, on a throwaway
copy of the context, produces a real ranking from real evidence for a fraction of a second's work and
**zero model calls**. That is a *snapshot*, and Phase 14.7 emits one after every analysis batch.

#### 2.13.1 What a provisional answer may claim

Two rules, both arithmetic rather than taste.

**Counts are safe; percentages are not.** The respondent pool `P` (§4.1) is the denominator, and it
grows as more comments are analysed:

| Quantity | Can it go down as analysis continues? |
|---|---|
| `supporterCount(e)`, `weightedScore(e)`, the respondent pool `P` | **No** — they only grow |
| `share(e)` — the count divided by that pool | **Yes** |
| rank order | **Yes** |

A count shown at 60 s is still true at 290 s — incomplete, not wrong. A share shown at 60 s can be
flatly contradicted later, because the denominator moves under every entity at once. There is a
second and cleaner reason: §4.4 fixes the wording of that label exactly — *"X% of people who answered
mentioned this"* — and while analysis is running, "people who answered" is not a closed set. The
sentence has no truth value yet. **So percentages are withheld until the corpus closes**, by the same
mechanism §8.1 rule 2 already uses for a degraded run, and for a related reason: in both cases the
denominator is not a sample of anything.

**Rank order moving is fine.** Under an explicit provisional label a list that reorders is behaving
as promised; one that held still would imply a stability it does not have. Only the final state is
persisted as the run's result, so no intermediate ordering can reach it.

**Provisional never means padded.** §4.4's rule holds unchanged: five supporters or it is not a
strong result, and fewer qualify is fewer shown. After the first wave of batches the strong list is
often empty, which is why a provisional payload carries the **weak list** too — the honest early
picture is *candidates so far*, filling before it reorders, not a podium with gaps in it.

**The weak list holds two different things, and they must not share a label.** §4.4 both sets a
threshold (five independent users) *and* caps the headline list at five results, so `weak_results`
contains entities that are not yet a recommendation **and** entities with many supporters that
merely lost a seat to the cap — in the first real run, Arkansas at 28 supporters sat one place below
a top five that started at 56. Describing those as "fewer than five people recommended this" states
something false about a real count, which is §0.1's failure mode in miniature: a presentational
claim the evidence does not support. The results response therefore carries
`minimum_independent_users`, and the view labels the two groups separately — *also ranked* and *not
enough people yet*.

**The denominator is a fact about the run, not about a row.** `respondent_pool_size` is identical on
every result, so while percentages are withheld and there is no share for it to explain, it is
stated once for the page rather than repeated beside each entity's own supporter count, where the
two numbers read as one. The row keeps what is genuinely its own: how many discussions its
supporters came from.

#### 2.13.2 Snapshots are ephemeral, and nothing may be derived from them

§2.12 fixed the analysis merge in **batch order, never completion order**, so two runs over one
corpus produce identical statistics and identical suppressions. Snapshots necessarily arrive in
completion order. Both are correct, and they cannot be the same thing:

> **Binding rule.** A snapshot is display state. The sequence of snapshots is not reproducible; only
> the final state is, and only the final state is the record. No statistic, suppression, diagnostic
> or terminal status may be derived from a snapshot, and a run's persisted result is always the
> output of the full step 8-12 pass.

Two consequences fall out of it. Aggregation settles the run's terminal status (§7.1), so a snapshot
must read **only** `results` and `weak_results` off its throwaway copy and discard everything else —
copying anything more back would have a run announce itself finished sixty seconds in. And entity
resolution runs in a deterministic-only mode for snapshots: the catalogue and normalisation resolve
most names for free, an unresolved name is simply not counted, and the snapshot therefore
*under*-reports rather than over-reports. That is the safe direction, and it costs no model call.

**The counts must never go backwards.** The first wave of batches finishes within seconds of itself;
naively that is one snapshot computation and one database write per batch, racing each other, and a
snapshot covering three batches landing after one covering five makes the numbers on screen go *down*
— breaking the single promise that makes a provisional answer safe to show. Two guards, both
required: **single-flight with coalescing** (a computation already running marks the state dirty and
recomputes once afterwards, rather than queueing one per batch) and a **sequence number** counting
the batches a snapshot covers, so a lower one is never persisted over a higher one. Coalescing also
sets the update rhythm — roughly one per wave — with no timer to tune.

#### 2.13.3 The API contract

`analyzing` already exists as a status and is already set before analysis begins, so no new status is
needed. What changes is that it becomes a status with a results object:

- `GET /research/{id}/results` serves `analyzing`, with `provisional: true`;
- the response carries `weak_results` alongside `results`, each labelled for what it is, plus
  `minimum_independent_users` so a client can say *why* an entity is in the weak list;
- `share` is **`null`**, never `0`, and `percentages_suppressed` is true.

That last point is the load-bearing one. §0.1 requires a provisional response to be distinguishable
from a final one **by a client that ignores the flag** — a screenshot, a cached response or a naive
consumer must not be able to render an unfinished ranking as a settled one. A null share is a hole a
naive client cannot fill in; a zero is a number it would print.

A thin provisional run must also stay distinguishable from a thin *suppressed* one (§0.1). It is:
`provisional` says the corpus is still open, `diagnostics.suppressions` says what was lost, and the
two appear in the same payload without overlapping.

**§7.1 is amended in one row.** `cancelled` previously promised no results page at all. A run
cancelled during analysis has now already produced snapshots from evidence the user paid for, and
throwing them away to show an empty page serves nobody — it is the same waste §2.12.2 refuses when
it lets in-flight batches finish. So: **a cancelled run serves a results object when, and only when,
it holds a provisional snapshot**, marked `provisional: true` with percentages withheld and its own
wording; a cancelled run with no snapshot behaves exactly as before. Every other "No" in §7.1 is
unchanged — `failed`, `rejected` and `source_unavailable` still have no results object, because in
those cases there is no evidence, which is a different thing from unfinished evidence.

#### 2.13.4 Explicitly out of scope

- **Anything that makes the pipeline faster.** Step timing, batch size, provider tuning, and the
  breadth ceiling §2.12.3 found in retrieval are all real and all tracked separately. With 14.7 alone
  the first snapshot lands when the first analysis wave returns — after discovery, triage and
  retrieval have run. *That is the feature working correctly*, and it must not be judged as a latency
  result.
- **Shrinking the analysis batch to snapshot sooner.** Measured in §2.12: per-call latency is mostly
  fixed cost, not output size. Smaller batches would produce the first snapshot a few seconds earlier
  carrying so little evidence that nothing clears §4.4's five-supporter line — so the first *useful*
  snapshot would arrive later.
- **Showing anything the model believes.** The quick route to a ranking in ten seconds is to ask the
  model what it thinks and replace it with evidence later. That is §0.1 in its purest form — a prior
  wearing the clothes of a finding — in the position that anchors the whole answer. Every provisional
  number is computed from analysed comments, or it is not shown.

Two follow-ups are understood and deliberately excluded: **showing the evidence as it is gathered**
(discovery and triage already know which discussions were found and which count, long before any
ranking exists — it is not a ranking and must not be dressed as one), and **analysing before
retrieval finishes** (breadth-first fetching would let the first wave go out much earlier). The second
changes *when* evidence arrives; 14.7 establishes *whether it can be shown at all*, and every rule
about what a half-finished answer may claim. Reordering first would mean faster evidence and still no
way to put it on screen.

---

### 2.14 One minute, and the first place has a hundred people behind it — **Phase 14.8 added**

Three targets, set by the product owner after running 14.7 against a real corpus. They are
requirements, not derivations:

1. **The top result carries >= 100 supporters.**
2. **A settled answer within 60 seconds.**
3. **Nothing is paid for that the metric cannot use.**

#### 2.14.1 What the targets cost, from measured numbers

The measured run analysed 840 comments and produced a respondent pool of 417, in which the top
result held 56 — 0.496 respondents per analysed comment, 13.4 % of the pool at the top. A top result
of 100 therefore needs a pool of ~745 and **~1500 analysed comments: 1.8x, not 3x.**

At 20 comments per call that is 75 calls. Per-call latency is ~25 s and **does not shrink when the
response does** — §2.12.3 measured a 50.2 % smaller payload at 25.6 s against 23.2 s. Latency is
fixed cost per call, so the only way 75 calls fit inside a minute is to stop running them in waves:
**one wave, ~80 in flight, ~25 s**, behind a pre-roll of at most 8 s. Everything else follows from
that single arithmetic fact.

This is why 14.8 is a pipeline and not a bigger budget. Today's run spends ~135 s before the first
analysis call is issued — discovery (56.6 s, fully sequential), triage, then retrieval of every
document — and all of it is dead time the minute cannot afford.

#### 2.14.2 Strands

A **strand** is one document, carried end to end by one task: fetch, cap, pre-filter, analyse,
accumulate. Strands do not wait for each other, and a strand that fails removes only its own
contribution. Documents are independent — nothing in retrieval, pre-filtering or the analysis prompt
reads another document — so the sequential step list for §4.6 steps 5-7 was ordering by habit, not a
data dependency.

**Two things are genuinely shared, and neither is a barrier.**

- **The purse.** One budget for comments, analysis items and cost. A strand asks for a quota and is
  answered immediately. Without it a single 4000-comment thread spends everything, which is what
  §2.12.3's finding 1 observed happening in document order.
- **The denominator.** One person, one vote holds across strands, so counting is local and the
  union is global. That union already exists: it is 14.7's snapshot over the accumulated analyses
  (§2.13.2), unchanged.

Concurrency is bounded on **model calls, not on strands** — that is where the money and the provider's
rate limit are. Strands are cheap; calls are not.

**§4.5's budget priority becomes a reservation, not an ordering.** Polling-first was implemented as a
sorted queue, which cannot survive arrival-order processing. A topical quota replaces it, and is
strictly better than what it replaces: in the measured run topical documents received *nothing*
(`topical_comments_retrieved: 0`), because polling documents consumed the whole budget first.

**§8.1's health assessment becomes a gate plus a continuous reading.** It ran as a barrier between
retrieval and analysis precisely so that money is not spent on a corpus a broken source produced.
Streaming cannot keep the barrier, so it keeps the guarantee a different way: no analysis call is
admitted until `minPostsRetrieved` documents have been fetched successfully, and the assessment is
re-read as the run proceeds. `assess_source_health` is already a pure function over the recorder's
snapshot, so this is a call-site change. §2.13.2 covers the rest: a snapshot is display state, and a
run that reaches `source_unavailable` clears it.

#### 2.14.3 Not paying for what the metric discards

The measured run extracted 2197 entity mentions and **discarded 1256 of them as off-granularity —
57 %** — because the analysis prompt asks for every place at every tier while a state-tier question
can use only one. The prompt carries the plan's granularity. This is a **cost** change, and the plan
says so plainly: §2.12.3 already established that a smaller response is not a faster one, and no
latency claim is made for it here.

#### 2.14.4 Out of scope

**Stability across runs is not claimed by this phase.** It is a real defect — the corpus is drawn by
an agentic discovery loop that proposes different queries each run, so two runs of one query sample
different threads — and the measured pool of 417 additionally leaves ranks 2 through 8 statistically
inseparable (New York vs Oregon: 0.65 sigma). 14.8 makes runs *bigger and faster*, which narrows the
second problem and not the first. Naming it here so that a later phase inherits a stated problem
rather than rediscovering it.

### 2.15 A run is answered once and kept — **Phases 14.9, 14.10, 14.11 added**

Every run this product has ever performed is already in the `research` table: the question, the
plan, the ranking, the statistics, the diagnostics. None of it can be reached again. A finished
run lives exactly as long as the browser tab that started it, and the only way to look at an answer
a second time is to buy it a second time.

That cost two real verification cycles during 14.8 — twice a result was on screen without the
explanations it had in fact produced, and both times the only way to check was to pay for another
run. It also makes the product quietly dishonest about its own economics: a question asked twice in
a week is answered twice, from a corpus of Reddit threads up to fifteen years old that did not
change in between.

Three phases, in this order, and the order is the argument.

**14.9 — history.** A list of past runs, and a URL per run. This is almost entirely exposure: the
data is stored, the results endpoint already serves any id, and the frontend simply has no route to
reach one. It is first because everything after it needs a way to show the user a run that is not
the one they just started — a reused answer is useless if it cannot be opened, compared, or
distrusted.

**14.10 — answering a question that has already been answered.** The reuse key is **not** the raw
text: "best states for nature" and "Best states for nature?" are the same question and would miss
each other. It is the **plan** — normalised query, scope, granularity, criteria — which Query
Understanding produces anyway, for one call out of roughly a hundred and thirty. Paying one cheap
call to skip the other hundred and twenty-nine is the trade, and it has the property raw text cannot
have: two differently worded questions that mean the same thing land on the same answer.

The window is **six months**, configurable. That is long, deliberately. The corpus is Reddit threads
admitted up to fifteen years old; a fortnight changes nothing in it, and the honest constraint on
reuse is not freshness but consent — the user must always be able to say *no, run it again*, and must
never be shown an old answer that looks new.

So two rules govern reuse, and they are not negotiable:

1. **A reused answer says when it was produced**, on the page, in the same place a provisional run
   says it is provisional. §2.13.2 established that display state must never be mistaken for a fresh
   finding; an answer from March presented as an answer from today is that same error with a longer
   fuse.
2. **A fresh run is always one click away**, and it never consults the cache.

This phase also records what each call spent, because that is what turns "the cache saves money"
from an assertion into a reading. Nothing in this codebase counts a token today. The totals are the
minimum needed to compare a hit against a miss; deciding what to *do* about the number is 14.11's
job, not this one's.

**14.11 — a cap on spend.** `maxEstimatedCostUsd` has been in `ResearchBudget` since Phase 1 and is
read by no line of code — a knob that lies, which is the same failure this plan forbids everywhere
else. Measured across two real runs the shape is already clear: 85–126 analysis calls against
3 342–3 996 comments, and every other step combined is about thirty calls. This phase makes the knob
real, and adds the provider-side prompt caching the analysis prefix is already shaped for — the
instructions and plan are byte-identical across every batch of a run, and only the comments change.

**A cap on LLM spend is possible, but not exactly.** No provider will say what a call costs before it
is made. What is available is the exact usage of every call *after* it returns, and a local token
count of a prompt *before* it is sent. So the cap is enforced the way `maxResearchDuration` already
is — as an admission rule, not a guarantee. Before each analysis batch, the estimated input cost plus
the worst case for `maxOutputTokens` is checked against what is left in the purse; if it does not
fit, the batch is never dispatched and the refusal is recorded. A run can overshoot by at most the
one batch that was in flight, and it can never overshoot silently. This is the same shape as §2.12.2's
admission deadline, and it belongs in the same purse.

It is **last** because a cap is a policy about a number, and the number arrives in 14.10. Ordering it
earlier would mean choosing a limit before anything had measured what a run actually spends.


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
│   │   │   └── ports.py             # SourceAdapter, WebSearchProvider, LLMProvider protocols
│   │   ├── pipeline/
│   │   │   ├── base.py              # PipelineStep protocol, context, progress
│   │   │   ├── runner.py
│   │   │   └── steps/               # one module per step
│   │   ├── sources/
│   │   │   ├── tools.py             # agent-facing tool boundary
│   │   │   ├── arctic_shift/        # retrieval adapter
│   │   │   └── fake/                # fixture-backed adapter for tests
│   │   ├── search/                  # WebSearchProvider impls (serper, fake) — §2.11
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
| 3 | Agentic Source Discovery | **AI** | Bounded, via the web search tool; hydrated through the source adapter (§2.11) |
| 4 | **Source Document Triage** | **AI** + rules | **New — §4.7. Gates everything downstream** |
| 5 | Content Retrieval | no | Comment trees for surviving documents only |
| 6 | Cheap Pre-filtering | no | Heuristics; **budget spread across every document** (§2.12); embeddings deferred |
| 7 | Comment Analysis | **AI** | Merged relevance + entity + opinion (§5). **Batches run concurrently and fail independently** (§2.12) |
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
    reason_code: ReasonCode        # closed enum, for debugging — see §2.12
```

`reasoning` became `reason_code`, a closed enum: the free-text sentence was 50.2 % of the response
payload and nobody read it. An enum can be *counted*, which is what §0.1 wanted from it — a thin
run can now say whether its corpus was off topic, out of scope or simply mute.

**The latency argument for this change did not survive measurement** (§2.12.3). 14.6a was written
expecting a smaller response to be a faster one; the verification run shows median batch latency of
25.6 s against 23.2 s before, both at `effort=low`. The change is justified by countability alone,
and the plan says so rather than leaving a tidier claim standing.

**`normalized_guess` was removed in §2.12, and not for the reason first written here.** Phase 9 did
consume it, in two places: as a fallback catalogue key when the verbatim surface form missed, and as
a `written_as:` hint in the resolution prompt. The first is the reason to remove it. A hit on a
*guessed* canonical name was recorded as `decided_by=RULE` at `confidence=1.0` — a model's judgement
wearing a catalogue's badge, in a step §4.6 calls "deterministic first". §2.12.1 established that
this model guesses wrong names confidently (`Lake Huron` → `Lake Michigan`), so the failure is not
hypothetical, and it was invisible: the resolution looked like a rule. The path was also untested —
every fixture set `normalized_guess = raw_text`, which makes the fallback ask the catalogue the same
question twice.

**The consequence, stated rather than discovered later.** Surface forms the catalogue does not hold
but whose guess it would have held now go to the AI resolution step instead of resolving by rule.
`entity_forms_resolved_by_rule` falls and `entity_forms_resolved_by_ai` rises by the same amount;
both are already in §8.1's statistics, so the shift is visible. Phase 15 measures whether AI
resolution recovers those forms as accurately, and at what cost.

**Anti-fabrication rule (`PROJECT.md` §29 "never silently invent evidence"):** every
`supporting_quote` is verified against the stored comment body — **normalised, then matched at
≥0.90 similarity** (§2.12.1). A mention whose quote does not reach the threshold is **discarded and
counted in a `fabricated_quote` metric**; every non-exact decision, accepted or rejected, is written
to the verification audit trail. This is a deterministic check, not a prompt instruction, and it is
tested.

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
| `cancelled` | User cancelled | **Only what it already had** — a provisional snapshot, labelled as one (§2.13.3). Nothing at all if it had none |

The distinction between `completed_partial` and `completed_degraded` is the whole point. The first
says *"we stopped early on purpose"* — `PROJECT.md` §21's graceful stop, and the evidence gathered
is a valid sample. The second says *"we could not see properly"* — the evidence may be arbitrarily
biased by which requests happened to succeed, and no honest percentage can be computed from it.

**Binding rule:** a thin result set may be reported as a genuine finding **only** when source health
passed. Otherwise the shortfall is attributed to the source, never to Reddit's opinions.

---

## 8. Source access — Arctic Shift

Base URL `https://arctic-shift.photon-reddit.com`. No authentication.

**Retrieval only** since §2.11 — discovery happens through the web search provider, and no endpoint
below performs a keyword search.

| Endpoint | Use |
|---|---|
| `/api/posts/ids` | **Hydration.** Up to 500 post ids per call — the ids discovery extracted from search results |
| `/api/comments/search?link_id=…` | Comment tree for one post |
| `/api/subreddits/search` | Find relevant communities |

The ID-addressed endpoints are the reliable half of this service (§2.11): measured 6/6 successes at
0.2–1.0 s, against 1/5 at 5.5–11 s for keyword search.

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

Since §2.11 a research depends on **two** external services: the web search provider for discovery
and Arctic Shift for retrieval. The logic below was already written for **N adapters**, so the
rules are unchanged — each is recorded under its own name, and either one failing every call is a
rule-1 `source_unavailable`. Note the asymmetry the rules already handle correctly: a dead search
provider yields *no documents to retrieve*, which must be reported as an outage and never as a
query about which Reddit had nothing to say.

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

**The LLM is accounted the same way (§2.12).** From Phase 14.6 an analysis batch that fails is
isolated rather than fatal, which means the run can now finish having analysed less than it
retrieved. That gap is evidence suppression under §0.1, so it is recorded exactly like a source
failure — batches attempted, batches failed, comments lost, failure kinds — and it feeds rule 2's
`comments_analyzed`. A run that lost a quarter of its comments to LLM errors must not be
presentable as a run that found little.

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

**`FakeSearchProvider`** (§2.11) follows the identical rule: fixture-backed Reddit results,
offline, able to simulate an empty result set and a total provider outage, and the **default** —
`SEARCH_PROVIDER` must be set explicitly to reach Serper, so no test run can spend a query quota.

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
| **14.5** | **Search-backed discovery** | 6, 14 | **§2.11. `WebSearchProvider` port, fake + Serper impls, `SEARCH_PROVIDER` default fake, Reddit-URL → post-id extraction, batch hydration via `posts/ids`, discovery step rewritten, §8.1 accounting over both dependencies** |
| **14.6** | **Throughput and sampling breadth** | 14.5 | **§2.12. Enum reason codes replace prose, concurrent analysis batches, configurable `reasoning.effort` (default `low`), per-batch failure isolation, per-thread sampling with comment `score`, `maxResearchDuration` enforced as an admission gate (in-flight work always finishes), fuzzy quote verification + audit trail** |
| **14.7** | **Streaming provisional results** | 14.6 | **§2.13. Snapshot function re-running steps 8-11 over the partial corpus with no model call, a snapshot emitted after every analysis batch (single-flight, coalesced, sequence-guarded), `analyzing` served by `/results` as `provisional` with `share: null` and the weak list alongside, a provisional results view that fills before it reorders** |
| **14.8** | **Parallel strands** | 14.7 | **§2.14. One document = one strand, carried end to end and concurrently; shared budget and shared denominator replace the sequential step list for §4.6 steps 5-7; per-document comment cap; topical quota replaces polling-first ordering; health gate plus continuous reading; granularity-restricted analysis prompt** |
| **14.9** | **Run history** | 14.8 | **§2.15. A list of past runs and a URL per run; the results a run already produced are reachable without re-running it** |
| **14.10** | **Answering a question once** | 14.9 | **§2.15. Reuse keyed on the research plan, not the raw text; six-month window; a reused answer is dated on the page and a fresh run is always available; token usage recorded per run, so the saving is read rather than claimed** |
| **14.11** | **A cap on spend** | 14.10 | **§2.15. `maxEstimatedCostUsd` enforced as an admission rule in the purse; per-step cost attribution; provider-side prompt caching for the analysis prefix** |
| 15 | Evaluation | 14.6, 14.7, 14.8, 14.10 | Benchmark queries, precision measurement, cost/latency, weakest-stage analysis |

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

**Phase 14.5 — acceptance (§2.11):** a full research reaches ranked results with
`SEARCH_PROVIDER=fake` and **zero network calls**; a search provider that fails every call yields
`source_unavailable` with no results object, worded so it cannot be read as "Reddit had little to
say"; a non-post Reddit URL (subreddit page, user page, comment permalink of an unknown post) is
discarded before any hydrate call; hydration batches at most 500 ids per request; the discovery
loop still cannot exceed `maxSearchQueries` or issue a near-duplicate query; §8.1 health records
the search provider and Arctic Shift separately.

**Phase 14.6 — acceptance (§2.12):** every kept document contributes comments to analysis whenever
the budget allows more than one per document, and a test proves no single document can consume the
whole budget while others get none; analysis batches run concurrently under a configured ceiling,
and a test proves the ceiling is respected; one batch failing leaves every other batch's result in
place, is recorded in §8.1 with its count, and a test proves the resulting run is distinguishable
from a genuinely thin one; `maxResearchDuration` is enforced by refusing to admit new work, and a
test proves that a batch in flight when the deadline passes is still awaited and its result kept,
that no batch is dispatched after it, and that a run which has already analysed something always
reaches a persisted result; expiry yields `completed_partial` naming the limiting factor, never
`completed`, and undispatched comments are counted separately from comments lost to errors;
`reasoning.effort` is read from
config with a documented default and no model parameter is hard-coded outside it; quote
verification accepts a normalised ≥0.90 match and records every non-exact decision — accepted and
rejected — with claimed quote, best-matching span, score and verdict, retrievable for review.


**Phase 14.7 — acceptance (§2.13):** a run reports a ranked, non-empty provisional result **before**
its analysis step completes, marked provisional, with `share` null; a snapshot and a full aggregation
produce identical output over an identical closed corpus, proven by a test that runs both; a snapshot
issues **zero** model calls, proven against a counting fake provider; a provisional response whose
strong list is empty still carries the weak list, and the view renders it as candidates rather than
as an empty ranking — nothing is ever padded to reach five, and an entity that missed only §4.4's
cap of five headline slots is never described as having too few supporters; a run cancelled during analysis still
reports the evidence it had, marked provisional, and one cancelled with no snapshot still has no
results object; a client that ignores `provisional` shows no percentage, because `share` is null and
not zero; no snapshot is persisted as a run's result and no statistic, suppression or terminal status
is derived from one, proven by a test that snapshots a context and asserts it is unchanged; §0.1: a
provisional run that is thin *because it is early* is distinguishable in the payload from one that is
thin *because evidence was lost*; and the counts a client sees never decrease, proven against
out-of-order batch completion.

**Phase 15 — benchmarks:** underrated US states for nature; US national parks avoiding crowds;
underrated European road-trip regions; best regions for cycling and nature. For each: inspect a
sample of retrieved comments by hand, measure relevance precision, check entity resolution and
deduplication, compare ranking against manually reviewed evidence, record cost and latency.
**Identify the weakest stage before optimizing anything** (`PROJECT.md` §27).

**Phase 14.8 — acceptance (§2.14):** the three targets are measured on one real run, not argued.
**(a)** the top result carries **>= 100 supporters** and the respondent pool is **>= 745**;
**(b)** the run reaches a settled answer **within 60 s**, of which at most **8 s** precede the first
analysis call; **(c)** **>= 60 documents** contribute counted comments, against 12 in the §2.12.3
run; **(d)** a strand failed on purpose removes **only its own contribution**, the run still reports,
and the loss is visible in `diagnostics.suppressions` — the §0.1 test, run against a concurrent
pipeline rather than a sequential one; **(e)** no model call is admitted after the dispatch deadline,
and none is admitted before `minPostsRetrieved` documents have been fetched; **(f)**
`entity_mentions_off_granularity` falls to **under 10 %** of `entity_mentions_total`, from 57 %.
Stability across runs is explicitly **not** an acceptance criterion (§2.14.4).

**Phase 14.9 — acceptance (§2.15):** a run started, finished and then navigated away from can be
reopened at its own URL and shows the same ranking, explanations, statistics and diagnostics it
showed when it finished, with no new model or source call made; a history page lists past runs
newest first with their question, date and outcome, and distinguishes a `completed` run from a
`completed_partial`, `failed` or `cancelled` one at a glance; a run still in flight is reachable at
the same URL and shows its progress rather than a dead page; and the history page says plainly when
it is empty rather than rendering as though it had failed to load.

**Phase 14.10 — acceptance (§2.15):** a question whose plan matches a `completed` run inside the
reuse window returns that run's answer without a discovery, retrieval or analysis call; a question
worded differently but with an identical plan hits the same run, and one whose scope, granularity or
criteria differ does not; a run older than the window is never reused; a reused answer is labelled
with the date it was produced, everywhere that answer is shown, and a test proves the label cannot be
absent; asking for a fresh run bypasses the cache entirely and produces a new run with its own id,
leaving the old one intact in the history; a cache hit on a `completed_partial`, `failed` or
`cancelled` run is refused — only a run that actually finished may answer for a later question; and
every LLM call records the tokens it used and the run carries the totals in `statistics`, so the
saving a hit produces is a number on the two runs rather than a claim about them.

**Phase 14.11 — acceptance (§2.15):** `maxEstimatedCostUsd` refuses to admit an analysis batch
whose estimated cost does not fit what is left in the purse, records the refusal as a suppression
with its count and the limit that bound it, and yields `completed_partial` naming cost as the
limiting factor — never `completed`; a test proves a run stopped by cost is distinguishable from one
that genuinely found little (§0.1); a run that would exceed its cap by a single in-flight batch
finishes that batch and dispatches no other; per-step cost attribution is visible, so the claim that
analysis dominates a run is read off the run rather than assumed; and prices live in config, never in
`domain/`.

---

## 11. API surface

```
POST   /api/research                    -> {id, status}   (14.10: may answer from a previous run;
                                           `fresh=true` never does)
GET    /api/research                    -> 14.9: past runs, newest first, paginated
GET    /api/research/{id}               -> status, progress, statistics, budget used, and
                                           (14.9) the question asked and the date it was asked,
                                           since a run is now opened by people who did not start it
POST   /api/research/{id}/clarify       -> answer a ClarificationRequest, resume
GET    /api/research/{id}/results       -> ranked results, strong and weak (§2.13.3: also
                                           served while `analyzing`, flagged `provisional`)
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
