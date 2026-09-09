> ## ⚠ Read `implementation-plan.md` first
>
> This document is the **product and architecture brief** — it explains *why*, and its principles
> (§6) and engineering constraints (§29) remain binding.
>
> `implementation-plan.md` is the **executable brief** and **wins on any conflict**. It resolves the
> decisions deferred here and corrects several since superseded:
>
> | Section | Status |
> |---|---|
> | §11 Reddit Integration | **Superseded** — MVP source is Arctic Shift, not the Reddit API |
> | §12 Research Pipeline | **Superseded** — see plan §4.6 (steps merged, triage + clarification added) |
> | §19 / §24 percentage & chart | **Superseded** — see plan §4 (counts lead, bars only, never a pie) |
> | §27 Implementation Roadmap | **Superseded** — see plan §10 (adds the Phase 3.5 walking skeleton) |
> | §31 Technology Selection | **Resolved** — see plan §1 |
>
> Everything else here stands.

# Opinion-Based Travel Research Engine

## 1. Project Vision

Build a web application that answers open-ended travel research questions by finding and aggregating opinions from online communities.

The first source is Reddit. The architecture must remain source-agnostic so additional sources can be added later without changing the core research domain.

Example query:

> Most underrated destinations in the US for nature

Example result:

1. Alaska — 42%
2. Oregon — 21%
3. New Mexico — 14%

Each result should include a concise explanation and traceable evidence back to the underlying Reddit discussions/comments.

The system must not present an AI-generated opinion as fact. It should present an aggregation of analyzed opinions and clearly expose the evidence behind the result.

---

## 2. MVP Scope

### In scope

- Web UI for entering a natural-language travel research query.
- Backend API.
- Reddit as the first source.
- AI-assisted query understanding and query expansion.
- Reddit post/comment discovery and retrieval.
- Semantic relevance analysis.
- Destination/entity extraction and normalization.
- Opinion extraction.
- Independent-user deduplication.
- Configurable time weighting.
- Deterministic aggregation and ranking.
- Top 5 results when enough evidence exists.
- Fewer than 5 results when evidence is insufficient.
- Minimum independent-user evidence threshold.
- Short AI-generated explanation per result.
- Evidence linking to source posts/comments.
- Persisted research snapshots.
- Configurable research budgets/limits.
- Automated tests at every implementation step.

### Explicitly out of scope for MVP

- Additional sources beyond Reddit.
- Personalized decision-tree travel matching.
- Accounts/authentication unless required by deployment.
- Social features.
- Booking.
- Restaurants and non-travel recommendation domains.
- Upvote-based weighting.
- Microservice deployment.

---

## 3. Future Direction

The architecture should later support:

### Additional sources

Examples:
- Web search
- Travel forums
- YouTube
- Other communities

Each source should implement the same source-facing contract while remaining independent of the core domain.

### Personalized candidate refinement

A future feature may take the initial set of strong candidates and discover the dimensions that distinguish them.

Example:

1. Research finds 20 strong US nature destinations.
2. The system analyzes how they differ.
3. It identifies useful dimensions such as climate, remoteness, landscape, culture, crowds, road-trip suitability, and cycling.
4. The user answers targeted questions.
5. The system ranks the candidates against the user's preferences.

Important: do not implement this in the MVP, but do not design the MVP in a way that prevents it.

---

# 4. Architecture Decision

## Recommended architecture

Use:

**Modular Monolith + Ports & Adapters + Research Pipeline + Asynchronous Research Jobs**

Do NOT start with microservices.

### Why

The product has several logical modules, but they do not currently need independent deployment or independent scaling. Microservices would add operational complexity without solving an existing problem.

The code should nevertheless have strong module boundaries so individual components can later be extracted into services if real scaling requirements justify it.

---

# 5. High-Level Architecture

```text
                    WEB FRONTEND
                         |
                         v
                    BACKEND API
                         |
                         v
                 RESEARCH JOB
                         |
                         v
               RESEARCH PIPELINE
                         |
        +----------------+----------------+
        |                |                |
        v                v                v
    DISCOVERY         ANALYSIS         RANKING
        |                |                |
        v                v                v
   SOURCE PORTS      AI / RULES       DOMAIN CODE
        |                |
        v                v
     Reddit            AI Provider
                         |
                         v
                      STORAGE
```

The backend should expose an API, while long-running research should execute as asynchronous jobs.

The frontend must not know how Reddit, AI, ranking, or storage work internally.

---

# 6. Core Architectural Principles

1. Keep domain logic independent of frameworks.
2. Keep external services behind ports/adapters.
3. Treat AI as a tool used by individual pipeline steps, not as the architecture itself.
4. Prefer deterministic code for aggregation, ranking, validation, and persistence.
5. Use AI where semantic understanding provides a meaningful advantage.
6. Keep every research run reproducible as a stored snapshot.
7. Make research limits configurable.
8. Make pipeline steps independently testable.
9. Prefer small modules with explicit inputs/outputs.
10. Do not add abstractions without a concrete reason.
11. Avoid premature microservices.
12. Make source integrations replaceable.

---

# 7. Domain Model

## Research

Represents one execution of a user's query.

Fields should include at least:

- id
- originalQuery
- normalizedQuery
- createdAt
- status
- source configuration
- research configuration
- statistics
- results

A repeated search creates a new Research record.

Old research is never silently overwritten.

## Entity

A generic travel destination/recommendation target.

Examples:

- US state
- city
- national park
- region
- beach
- hiking area
- island

The model must not assume a single destination type.

## SourceDocument

Represents a source post/thread or equivalent source item.

For Reddit this is a Reddit post.

## Comment

Represents an individual source comment.

Store enough source metadata to trace the comment back to Reddit.

## User

Represents the source-community author where available.

For Reddit, the username/author identifier is required for independent-opinion deduplication.

## Opinion

Represents a normalized opinion extracted from a comment.

Important fields:

- source comment
- source user
- entity
- relevance
- recommendation strength
- criteria matches
- timestamp
- analysis confidence

The system should distinguish a raw comment from the normalized opinion derived from it.

---

# 8. Query Understanding

Input:

> Most underrated US destinations for nature

The system should derive structured intent such as:

```text
scope: United States
entity type: travel destination
topic: nature
intent: recommendation
criterion: underrated
output: ranked recommendations
```

The representation must remain generic enough for future travel questions.

AI may be used here.

The result should be structured data validated by the application.

---

# 9. Query Expansion

The system may use AI to generate multiple semantically different search queries.

Example:

```text
underrated nature destinations USA
hidden nature gems USA
overlooked beautiful places USA
least touristy scenic destinations USA
best US wilderness destinations
...
```

The goal is coverage, not merely paraphrasing.

Search queries must be deduplicated and bounded by the research budget.

The application, not the LLM, controls the maximum number of searches.

---

# 10. Source Architecture

Use a source port/interface conceptually equivalent to:

```text
SourceAdapter
  - search(request)
  - fetchDocument(id)
  - fetchComments(document)
```

Reddit is the first adapter.

The research core must not contain Reddit-specific assumptions.

Future adapters should be addable without changing the Opinion, Entity, Aggregation, or Ranking domain models.

## Source capabilities as Agent Tools

Sources should expose their capabilities through a controlled tool boundary that can be used by the Research Agent.

Conceptually:

```text
Research Agent
      |
      v
Source Tool
      |
      v
Source Adapter
      |
      v
External API
```

For Reddit:

```text
Research Agent
      |
      v
Reddit Search Tool
      |
      v
RedditAdapter
      |
      v
Reddit API
```

The Research Agent decides which searches are useful. The adapter performs the actual API interaction.

The agent must NOT receive direct access to Reddit API credentials, URLs, pagination internals, rate-limit handling, or arbitrary network access.

The backend remains responsible for:

- authentication
- validation
- rate limits
- retries
- caching
- research budgets
- allowed parameters
- logging
- error handling

A future source may expose different capabilities, for example:

```text
Reddit:
  search
  fetch document
  fetch comments

Web:
  search
  fetch page

YouTube:
  search
  fetch transcript
```

The Research Agent should discover/use capabilities through a stable tool contract rather than knowing source-specific implementation details.

---

# 11. Reddit Integration

Investigate and use the most appropriate official/current Reddit API or supported Reddit access mechanism available at implementation time.

Do not hard-code assumptions about Reddit's current API limits or authentication behavior.

The adapter should handle:

- authentication/configuration
- search
- pagination
- post retrieval
- comment retrieval
- rate limits
- retries
- transient failures
- source URLs
- source timestamps
- author identity

Keep all Reddit-specific code inside the adapter.

---

# 12. Research Pipeline

The pipeline should be composed of small, independently testable steps.

The research process may contain an agentic discovery loop, but the overall workflow must remain bounded and observable.

Recommended initial order:

```text
1. Query Understanding
2. Research Planning
3. Agentic Source Discovery
4. Content Retrieval
5. Cheap Pre-filtering
6. Semantic Relevance Analysis
7. Entity Extraction
8. Entity Resolution
9. Opinion Extraction
10. User Deduplication
11. Time Weighting
12. Aggregation
13. Ranking
14. Result Summarization
15. Persistence
```

### Agentic Source Discovery

The Research Agent may repeatedly:

```text
decide search
    ↓
call source tool
    ↓
inspect returned metadata/results
    ↓
decide whether coverage is sufficient
    ↓
search again OR finish discovery
```

Example:

```text
User query
   ↓
Research Agent
   ↓
Reddit search: "underrated nature USA"
   ↓
inspect results
   ↓
Reddit search: "hidden nature gems USA"
   ↓
inspect results
   ↓
Reddit search in relevant communities
   ↓
coverage sufficient
```

This is preferable to hard-coding a fixed list of search queries.

However, the agent is always constrained by the Research Budget. The agent cannot perform unlimited searches.

Not every step requires AI.

---

# 13. AI Usage Strategy

AI should be treated as a replaceable tool and may appear in multiple pipeline stages.

There are two distinct AI roles:

### 1. Research Agent

The Research Agent plans and executes bounded discovery actions through approved tools.

It can:

- interpret the research objective;
- generate search strategies;
- call source tools;
- inspect returned search metadata;
- identify gaps in search coverage;
- request additional searches;
- decide when discovery is sufficiently covered.

It cannot:

- bypass research budgets;
- access external services directly;
- access secrets;
- modify persisted results arbitrarily;
- decide the final ranking;
- fabricate evidence.

### 2. Analysis Models

Separate AI calls can perform semantic analysis on retrieved content.

AI should be treated as a replaceable capability behind provider/task interfaces.

Potential AI tasks:

### Query Understanding
AI: yes

### Query Expansion
AI: yes

### Cheap pre-filtering
Prefer normal code / search metadata / embeddings where useful.

### Semantic relevance
AI or embeddings: yes

### Entity extraction
AI: likely yes

### Entity resolution
Use deterministic normalization first; use AI/embeddings for ambiguous cases.

### Opinion extraction
AI: yes

### User deduplication
Normal deterministic code.

### Time weighting
Normal deterministic code.

### Aggregation
Normal deterministic code.

### Ranking
Normal deterministic code.

### Result explanation
AI: yes

The exact model/provider must be evaluated during implementation based on cost, latency, quality, structured-output support, and availability.

Do not hard-code a specific model name into the domain layer.

---

# 14. Relevance Model

Do not use a simple keyword match.

A comment can be relevant even when it uses completely different wording.

Example:

> Alaska is totally underrated when it comes to nature.

and:

> Alaska has some of the most spectacular untouched wilderness in America.

can both be relevant to a query about underrated US nature destinations, but potentially with different confidence for the "underrated" criterion.

Model relevance as structured scores rather than a single boolean where useful.

Potential dimensions:

- topic relevance
- scope/entity relevance
- criterion relevance
- recommendation strength
- overall confidence

Use validated structured AI output.

---

# 15. Entity Resolution

Normalize different references to the same entity.

Examples:

```text
Alaska
AK
The Last Frontier
```

should resolve to the same canonical entity when context supports it.

Use:

1. deterministic normalization first;
2. known entity data where available;
3. semantic/AI resolution only for ambiguous cases.

Never silently merge entities when confidence is too low.

---

# 16. Opinion and User Deduplication

A comment is raw evidence.

An independent user is the primary unit for the percentage/ranking metric.

For MVP:

- one user should not be able to contribute unlimited independent votes for the same entity in one research;
- repeated recommendations by the same user should be deduplicated;
- 20 different users expressing the same opinion remain 20 independent opinions.

A practical initial rule:

```text
one user + one research + one entity = at most one counted opinion
```

Keep the underlying comments so evidence remains available.

---

# 17. Time Weighting

Do not hard-code the exact formula into the data model.

Store source timestamps and implement time weighting as a replaceable ranking component.

Initial candidate strategy:

```text
0 years old: 1.0
1 year:       0.9
2 years:      0.8
3 years:      0.7
...
```

The exact decay should be configurable and tested.

Avoid pretending that the initial formula is scientifically optimal. It is a product heuristic that should remain easy to change.

---

# 18. Upvotes

Do NOT use Reddit upvotes in MVP ranking.

Reason:

- voter identities are unavailable;
- voters may overlap with commenters;
- thread popularity can introduce unwanted bias;
- the product is intended to aggregate independent expressed opinions.

This decision can be revisited later as an experiment, but it must not be part of the initial score.

---

# 19. Aggregation and Ranking

The ranking should be deterministic.

AI should not directly decide the final ranking.

For each entity calculate at least:

- independent user count
- relevant comment count
- discussion count
- weighted opinion score
- evidence confidence

The primary percentage should represent the share of independent users recommending the entity within the relevant analyzed population.

Example:

```text
Alaska:
47 independent users

Oregon:
24 independent users

New Mexico:
15 independent users
```

The UI can show:

> 47 independent users

and a percentage derived from the defined aggregation population.

Keep the mathematical formula in one ranking/aggregation module so it can be changed and tested independently.

---

# 20. Evidence Threshold

Do not manufacture five results when evidence is weak.

A result should meet a configurable minimum independent-user threshold to be classified as a strong recommendation.

Initial MVP default:

```text
minimumIndependentUsers = 5
```

If only two destinations meet the threshold, show two.

Example:

> We found 2 strong recommendations.

Also expose the evidence counts so users can judge the strength themselves.

---

# 21. Research Budget

Research limits must be configurable at application level.

At minimum:

```text
maxSearchQueries
maxPostsPerQuery
maxTotalPosts
maxComments
maxAIAnalysisItems
maxResearchDuration
```

Optionally:

```text
maxEstimatedCost
```

The system must stop gracefully when a limit is reached.

A research must record the limits actually used so the snapshot can be understood later.

---

# 22. Asynchronous Jobs

Research can involve many external requests and AI calls.

Do not keep the browser request open for the entire research.

Recommended lifecycle:

```text
POST /research
      |
      v
create Research(status=pending)
      |
      v
enqueue job
      |
      v
worker executes pipeline
      |
      v
Research(status=completed)
```

The frontend can poll or use a future push mechanism for progress.

Store progress/statistics where useful:

```text
searches executed
posts discovered
comments retrieved
comments analyzed
opinions extracted
entities found
```

---

# 23. Persistence

Persist research snapshots.

At minimum, persist:

- research query
- configuration
- source metadata
- discovered documents
- comments
- users
- extracted opinions
- canonical entities
- analysis results
- final ranking
- evidence references
- timestamps
- pipeline/model metadata needed to understand the result

A repeated search creates a new research snapshot.

Caching may be used to avoid unnecessary repeated retrieval, but cached source data must not make two explicit research runs indistinguishable.

---

# 24. Frontend

The MVP UI should be deliberately simple.

### Search page

```text
What are you looking for?

[ Most underrated US destinations for nature ]

[ Search ]
```

### Research progress

Show that the system is researching and basic progress.

### Results

```text
Most underrated US destinations for nature

1. Alaska             42%
2. Oregon             21%
3. New Mexico         14%
...
```

Include:

- top 5 when evidence supports it
- fewer results when it does not
- distribution chart
- short explanation
- independent-user count
- discussion count
- evidence links

Avoid building complex filters or personalization in MVP.

---

# 25. API Boundary

The frontend should communicate only with the backend API.

Initial conceptual endpoints:

```text
POST /research
GET  /research/{id}
GET  /research/{id}/results
GET  /research/{id}/evidence
```

Exact endpoint structure may be adjusted during implementation.

The API should expose domain-level concepts, not Reddit API structures.

---

# 26. Testing Philosophy

Every implementation step must produce a testable increment.

An AI coding agent must not simply implement many modules and claim success.

For each step:

1. implement the smallest useful change;
2. write/update automated tests;
3. run formatting/linting/type checks;
4. run unit tests;
5. run integration tests where applicable;
6. verify expected behavior with a small fixture;
7. only then proceed to the next step.

Tests should include both normal and failure cases.

For AI-dependent steps, use deterministic fixtures/mocked model responses for most automated tests. Do not make the full test suite depend on live LLM calls.

Maintain a small set of optional evaluation tests against real models for quality measurement.

## Agent Tool Testing

Source tools must be tested independently from the underlying source adapters.

Test that:

- valid tool requests reach the adapter;
- invalid parameters are rejected;
- research budgets are enforced;
- the agent cannot request unlimited results;
- source-specific errors are normalized;
- credentials are never exposed to the agent;
- tool responses contain only the data required by the agent.

Use fake source tools in most agent tests.

## Agent Discovery Evaluation

Create deterministic scenarios where the expected discovery behavior is known.

Examples:

- direct query produces sufficient coverage;
- initial searches miss an important synonym and the agent performs another search;
- repeated/near-duplicate searches are rejected;
- search budget is exhausted;
- source returns insufficient data;
- source temporarily fails.

The goal is to test the agent's decision-making without requiring live Reddit calls.

---

# 27. Implementation Roadmap

The implementation should proceed in small, independently verifiable milestones.

## Phase 0 — Project Foundation

Goal:
Create the repository, development environment, CI, formatting, linting, type checking, and test framework.

Acceptance criteria:
- project starts locally;
- tests run;
- lint/type checks run;
- CI can execute them;
- no business functionality yet.

---

## Phase 1 — Domain Contracts

Goal:
Define core domain types and interfaces without Reddit or AI.

Implement:

- Research
- Entity
- SourceDocument
- Comment
- User
- Opinion
- Result
- Research configuration
- SourceAdapter contract
- AI capability contracts where needed

Tests:
- serialization/validation;
- invalid data rejected;
- domain objects can be constructed from fixtures.

Acceptance criteria:
The domain can be tested without network access or external services.

---

## Phase 2 — Deterministic Research Pipeline Skeleton

Goal:
Build the pipeline orchestration with fake adapters.

Implement:

- pipeline step contract;
- pipeline execution;
- progress/status;
- fake source;
- fake AI;
- deterministic fixtures.

Tests:
Run a complete fake research from query to result.

Acceptance criteria:
A full research can execute end-to-end without Reddit or an LLM.

---

## Phase 3 — Research Persistence

Goal:
Persist research jobs and snapshots.

Implement:

- database schema;
- repositories;
- research status;
- pipeline outputs;
- result persistence.

Tests:
- create research;
- resume/read research;
- completed research can be retrieved;
- separate runs remain separate.

Acceptance criteria:
Two identical searches produce two distinct persisted research records.

---

## Phase 4 — Reddit Adapter

Goal:
Connect the first real source.

Implement:

- Reddit authentication/configuration;
- search;
- pagination;
- document retrieval;
- comment retrieval;
- rate-limit handling;
- retries;
- source URLs.

Tests:
- adapter tests with mocked Reddit responses;
- pagination;
- malformed responses;
- rate limits;
- missing authors;
- deleted comments.

Acceptance criteria:
The pipeline can receive real Reddit content through the adapter while the core remains Reddit-agnostic.

---

## Phase 5 — Query Understanding + Expansion

Goal:
Turn natural language into a structured research plan and multiple search queries.

Implement:

- query model;
- AI structured output;
- query expansion;
- validation;
- deduplication;
- budget enforcement.

Tests:
Use fixed AI fixtures for known queries.

Acceptance criteria:
A query produces a validated research plan and bounded search-query set.

---

## Phase 6 — Agentic Source Discovery

Goal:
Allow a Research Agent to discover relevant Reddit discussions through the Reddit source tool while remaining strictly bounded.

Implement:

- source tool registration;
- Reddit search tool;
- tool input/output schemas;
- agent discovery loop;
- coverage/stop decision;
- duplicate-query prevention;
- research budget enforcement.

Tests:
- agent chooses useful search variants;
- agent can perform multiple searches;
- agent stops when coverage is sufficient;
- agent cannot exceed search limits;
- tool failures are handled correctly.

Acceptance criteria:
The agent can conduct a bounded multi-search Reddit discovery process without direct access to Reddit internals.

---

## Phase 7 — Retrieval and Pre-filtering

Goal:
Retrieve a bounded Reddit dataset efficiently.

Implement:

- search execution;
- deduplication of source documents;
- comment retrieval;
- cheap pre-filtering;
- research budgets.

Tests:
- duplicate posts;
- pagination;
- budget exhaustion;
- partial source failure;
- retry behavior.

Acceptance criteria:
The system can collect a bounded, traceable dataset.

---

## Phase 8 — Semantic Analysis

Goal:
Determine which comments actually answer the user's query.

Implement:

- relevance analysis;
- criterion matching;
- recommendation detection;
- structured confidence.

Use AI only where semantic understanding is required.

Tests:
Build a labeled fixture set containing:
- clearly relevant comments;
- indirectly relevant comments;
- irrelevant comments;
- ambiguous comments;
- differently worded but semantically equivalent recommendations.

Acceptance criteria:
The system handles semantic matches rather than relying on exact keywords.

---

## Phase 9 — Entity Extraction and Resolution

Goal:
Convert natural-language mentions into canonical destination entities.

Implement:

- extraction;
- deterministic normalization;
- entity resolution;
- ambiguity handling.

Tests:
- aliases;
- abbreviations;
- spelling differences;
- ambiguous regions;
- unrelated mentions.

Acceptance criteria:
Equivalent references resolve correctly and ambiguous cases are not silently merged.

---

## Phase 10 — Opinion Extraction + User Deduplication

Goal:
Produce normalized opinions and prevent one user from dominating the result.

Implement:

- opinion objects;
- recommendation strength;
- user identity;
- one-user-one-entity-per-research counting rule.

Tests:
- multiple comments by one user;
- multiple threads by one user;
- 20 different users with identical wording;
- deleted/anonymous authors.

Acceptance criteria:
The aggregation unit is independent users while raw comments remain available as evidence.

---

## Phase 11 — Weighting, Aggregation, Ranking

Goal:
Produce the actual quantitative result.

Implement:

- time weighting;
- aggregation;
- percentage calculation;
- evidence threshold;
- deterministic ranking.

Tests:
Create small hand-calculated datasets where the expected result is known exactly.

Acceptance criteria:
Ranking is reproducible and does not depend on an LLM deciding the order.

---

## Phase 12 — AI Summaries

Goal:
Generate concise explanations for ranked entities.

Input to AI should be structured evidence, not an uncontrolled dump of the entire dataset.

Tests:
- structured summary output;
- invalid model output;
- missing evidence;
- hallucination safeguards where practical.

Acceptance criteria:
Every displayed explanation can be traced to stored evidence.

---

## Phase 13 — Backend API

Goal:
Expose research functionality to the frontend.

Implement:
- create research;
- get research;
- progress/status;
- results;
- evidence.

Tests:
API integration tests.

Acceptance criteria:
The frontend can perform a complete research without accessing internal modules.

---

## Phase 14 — Frontend

Goal:
Build the minimal useful web experience.

Implement:
- search page;
- progress state;
- results page;
- ranking;
- percentage visualization;
- explanations;
- evidence links;
- insufficient-evidence state.

Tests:
- component tests;
- API integration;
- end-to-end happy path.

Acceptance criteria:
A user can enter a query and inspect a completed research result entirely through the website.

---

## Phase 15 — End-to-End Evaluation

Goal:
Validate the complete system against real travel queries.

Create a small benchmark set such as:

- underrated US nature destinations;
- best US national parks for avoiding crowds;
- underrated European road-trip destinations;
- best destinations for cycling + nature.

For each benchmark:
- manually inspect a sample of retrieved comments;
- measure relevance precision;
- inspect entity resolution;
- inspect user deduplication;
- compare ranking against manually reviewed evidence;
- record cost and latency.

Do not optimize blindly. Use these evaluations to identify the weakest pipeline stage.

---

# 28. Definition of Done

A feature is not complete merely because its code exists.

A milestone is complete only when:

- implementation exists;
- automated tests exist;
- tests pass;
- lint/type checks pass;
- failure cases are covered;
- the feature integrates with previous milestones;
- acceptance criteria are demonstrably satisfied.

The AI coding agent should report:

```text
Step:
Implemented:

Tests:
- ...
- ...

Validation:
- tests: PASS
- lint: PASS
- typecheck: PASS

Acceptance criteria:
- PASS
- PASS

Known limitations:
- ...
```

Then stop and wait for the next step rather than implementing the entire roadmap at once.

---

# 29. Important Engineering Constraints

- Prefer simple solutions.
- Avoid microservices for MVP.
- Avoid premature abstractions.
- Avoid framework-dependent domain logic.
- Avoid live LLM calls in normal automated tests.
- Never let an LLM directly control final ranking.
- Never silently invent evidence.
- Never fabricate source data.
- Preserve source traceability.
- Respect Reddit's current API terms, authentication requirements, rate limits, and applicable usage policies at implementation time.
- Keep secrets out of source control.
- Make external-service failures recoverable where practical.
- Make configuration explicit.
- Record enough metadata to understand how a research result was produced.

---

# 30. Suggested Repository Shape

The exact language/framework can be selected after validating current ecosystem/tooling requirements.

Conceptually:

```text
project/
├── frontend/
├── backend/
│   ├── domain/
│   ├── research/
│   ├── sources/
│   │   └── reddit/
│   ├── analysis/
│   ├── ranking/
│   ├── ai/
│   ├── persistence/
│   └── api/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── evaluation/
├── docs/
└── README.md
```

Keep this as a conceptual boundary, not a requirement to create a directory for every noun.

---

# 31. Technology Selection Rule

Do not choose technologies merely because they are familiar.

Before implementation, evaluate current options for:

- frontend framework;
- backend framework/runtime;
- database;
- job queue/background worker;
- Reddit API access;
- LLM provider/model;
- embedding/search technology if needed;
- hosting/deployment.

Choose the simplest mature option that fits the requirements.

The architecture is more important than the specific framework.

---

# 32. First Implementation Task

The first coding task should NOT be Reddit integration.

Start with:

> **Create the project foundation and domain contracts.**

The goal is to establish the boundaries that every later implementation must respect.

Then proceed one phase at a time.

The coding agent should never skip ahead to the complete application.

---

# 33. Architectural North Star

The system should ultimately make this possible:

```text
User
 |
 | "Most underrated US destinations for nature"
 v
Query Understanding
 |
 v
Research Plan
 |
 v
+-----------------------+
| Source Discovery      |
|                       |
| Reddit today          |
| Other sources later   |
+-----------+-----------+
            |
            v
       Raw Evidence
            |
            v
    Semantic Analysis
            |
            v
     Normalized Opinions
            |
            v
    Independent Users
            |
            v
       Aggregation
            |
            v
         Ranking
            |
            v
       Explanation
            |
            v
      Evidence-backed
          Results
```

The central idea is:

**AI interprets messy human language and can intelligently decide which approved research tools to use; deterministic software controls tool access, budgets, persistence, aggregation, and the final result.**

That separation should remain the guiding architectural principle throughout the project.
