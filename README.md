# TripFinder

**Ask a question. Get an answer counted from what people actually wrote.**

TripFinder is an opinion-research engine. You ask something like *"most underrated US states for
nature"* or *"best national parks for avoiding crowds"*, and it goes and finds the Reddit threads
where people answered that question, reads the comments, works out which places each commenter
recommends, de-duplicates them so one enthusiast is one vote, and ranks the result.

What comes back is not a model's opinion about travel. It is a count, with the comments it was
counted from attached:

> **#1 Canyonlands National Park — 47 people**
> *10 % of people who answered mentioned this. Based on 448 people across 14 discussions.*
> Travelers recommend Canyonlands because they describe it as really nice, a favorite, and much
> less visited and less crowded than Arches.
> [View evidence →]

---

## The one idea worth knowing

Most "AI research" tools ask a model what it thinks and dress the answer up as a finding. This one
is built around the opposite rule, and nearly every design decision follows from it:

> **A failure must never look like a finding.**

So: no language model decides the ranking — the maths is deterministic. Every quote shown is
verified to exist in the comment it is attributed to, and one that cannot be found is dropped and
counted as dropped. Every run reports what it *could not* read, and why, so a thin answer caused by
a broken source is distinguishable from a thin answer caused by nobody having an opinion. A run
that stops early says "stopped early", never "finished". A ranking that is still being counted
shows counts and **no percentages**, because the denominator is not final yet.

If you only read one file, read [`PROJECT.md`](PROJECT.md) — it is the argument behind all of that.
[`implementation-plan.md`](implementation-plan.md) is the build log, including the mistakes.

---

## What it does, step by step

1. **Understands the question** — normalises it, works out what kind of place is being asked about
   (state? country? national park?) and asks you if that is genuinely ambiguous.
2. **Searches** for discussions where people answer this kind of question, in several rounds, each
   one steered by what the previous round found.
3. **Triages** each thread: is it a question people *answered*, or just a thread about the topic?
   Does it keep your criteria, or has it drifted to something easier ("best" instead of
   "underrated")? Drifted threads are recorded, not counted.
4. **Reads the comments** — for each one, which places it names, whether it recommends or warns
   against them, how strongly, and a verbatim quote as evidence.
5. **Resolves names** — *Canyonlands*, *Canyonlands NP* and *the Needles district* are one place;
   the catalogue settles what it can for free, and only genuinely ambiguous names cost a model call.
6. **Counts** — one person, one vote per place, with a five-supporter floor so a single enthusiastic
   comment never becomes a recommendation.
7. **Explains** — a short summary per result, grounded in the stored quotes and rejected if it
   invents one.

You watch all of this happen: the ranking appears while the run is still reading and grows as it
goes, clearly marked as provisional until the corpus closes.

**A question already answered is not answered twice.** After step 1, the run is keyed on what the
question *means* rather than how it was typed — so "best states for nature" and "Best states for
nature?" land on the same answer — and if a finished run answered it within the last six months,
that run's counts are shown instead of a hundred and thirty more model calls being spent. The
answer always says the date it was produced, wherever it appears, and **"Research it again" is
always one click away and never looks at the cache**. Only a run that actually finished may answer
for a later question: a run cut short, degraded or cancelled never does.

---

## Running it

### You will need

- **Docker** (for Postgres only — everything else runs natively)
- **[uv](https://docs.astral.sh/uv/)** — owns the Python toolchain; you do not need Python installed
- **Node 22+**

### Setup

```bash
git clone https://github.com/loukra/TripFinder.git
cd TripFinder
cp .env.example .env                      # see "Keys" below
cd backend && uv sync && cd ..            # installs Python 3.12 and the deps
cd frontend && npm install && cd ..
make db                                   # Postgres in Docker
make migrate                              # create the schema (once)
```

Then three processes, in three terminals:

```bash
make api
```

```bash
make worker
```

```bash
make web
```

Open **http://localhost:3000**.

### Keys are required to run research

Both providers default to **`fake`**, and that default is a safety catch, not a demo mode: it exists
so that no test run and no fresh clone can bill an account or spend a search quota by accident. The
fake provider answers only the canned responses a test registered, so **an actual research run with
no keys configured fails at the first model call** — you will see a `failed` run, not a ranking.

What you *can* do without any account: start all three processes, browse the UI, and run the entire
test suite, which is a real exercise of the pipeline against fixtures.

### The two keys

Two services, both set in `.env`:

| Variable | What for | Where | Cost |
|---|---|---|---|
| `OPENAI_API_KEY` | Reading and classifying comments | [platform.openai.com](https://platform.openai.com) | pay-as-you-go |
| `SERPER_API_KEY` | Finding the threads (Google results) | [serper.dev](https://serper.dev) | 2 500 free queries, no card |

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

SEARCH_PROVIDER=serper
SERPER_API_KEY=...
```

Setting the key is not enough on its own — `LLM_PROVIDER` and `SEARCH_PROVIDER` must be switched
too, and a typo in either is a hard error rather than a silent fall back to fixtures. A run that
quietly used canned data would report fixture output as a finding, which is the one thing this
project refuses to do. It is also why there is no "try it without a key" mode: the only thing such a
mode could show you is invented, and this is not a codebase that shows you invented numbers.

Restart `make api` and `make worker` after changing `.env` — both read it at start-up.

**Reddit needs no key.** The comments come from
[Arctic Shift](https://arctic-shift.photon-reddit.com), a public archive, over a rate-limited and
politely user-agented client.

**What a run costs.** Measured on a real 5-minute run: about 3 400 comments read in ~125 analysis
calls, plus roughly 30 more for everything else. Nothing in this codebase counts tokens yet, and
`maxEstimatedCostUsd` exists in the config but is not enforced — that is a known, documented gap
(plan §2.15), not a promise. **Assume a run costs real money and watch your provider dashboard for
the first few.**

### Verifying

```bash
make lint && make typecheck && make test
```

No test ever calls a model or a live API — the providers default to fixtures, and the evaluation
tests that would cost money are marked and excluded. The integration tests do need Docker: they
start a throwaway Postgres and throw it away again. There is also a browser test:
`cd frontend && npx playwright test`.

---

## Swapping the services out

Both are behind ports — a `Protocol` with one method each — so neither OpenAI nor Serper is baked
in anywhere except one factory function.

### A different search API

`WebSearchProvider` is a single method:

```python
async def search(self, query: WebSearchQuery) -> Sequence[WebSearchHit]: ...
```

Implement it (Brave, Tavily, SerpAPI, Bing, your own index), add a value to `SearchProviderName` and
a branch to `build_search_provider` in `backend/src/tripfinder/search/factory.py`. That is the whole
change. The one thing your provider must tolerate is a `site:reddit.com` operator on every query.

### A different model

`LLMProvider` is also one method:

```python
async def complete_structured[T: BaseModel](self, *, prompt: str, response_model: type[T]) -> T: ...
```

Every call in the pipeline parses into a Pydantic model, so **the provider must support structured
output against a JSON schema.** That is the only hard requirement; nothing else about OpenAI leaks
past this line.

- **Anything OpenAI-compatible** — OpenRouter, Azure OpenAI, vLLM, Ollama, LM Studio — needs *no
  code at all*: set `base_url` on `OpenAIConfig`
  (`backend/src/tripfinder/ai/openai/config.py`) and change `model`.
- **Anything else** — Anthropic, Gemini, Bedrock — implement the protocol and add a branch to
  `build_llm_provider` in `backend/src/tripfinder/ai/factory.py`.

The model id lives in config and never in the domain layer, so changing it touches one line.

### A different source than Reddit

`SourceAdapter` is three methods (`health_check`, `fetch_documents`, `fetch_comments`). Nothing
above it knows what Reddit is — the pipeline sees documents with comments. A forum, a review site or
an internal corpus would slot in the same way. This one has only the Arctic Shift implementation
today, so you would also wire yours into the pipeline's composition root.

---

## Architecture, briefly

```
frontend/   Next.js + React. Polls a run; renders provisional and final rankings.
backend/
  domain/      models, config, ports. Imports no framework and no adapter.
  ranking/     the counting. Deterministic, no model, no I/O.
  analysis/    prompts and response schemas.
  pipeline/    the steps, the concurrency, the budget, the snapshots.
  sources/     Arctic Shift adapter.
  ai/ search/  provider implementations behind the ports.
  api/         FastAPI. Enforces what each status may and may not show.
  jobs/        Postgres-backed work queue; the worker leases a job and heartbeats.
```

A run is a row in Postgres and a job in a queue. The worker claims it, streams progress back, and
the API decides what a client is allowed to see at each status. `domain/` and `ranking/` import
nothing from the adapters, and a test enforces that.

---

## Status

Working and usable, and not finished. Built in numbered phases (see `implementation-plan.md` §10);
the current head is Phase 14.10. Known gaps are written down rather than hidden — the duration
budget governs only the dispatch of analysis rather than the whole run, and `maxEstimatedCostUsd`
is still a knob no code reads. Every run now records the tokens it spent, and separately how many
of its calls the provider reported no usage for, because an unmeasured call is unknown rather than
free; turning those tokens into money is the next phase's job.

Issues and pull requests welcome. If you find a case where a failure managed to look like a finding,
that is the most interesting bug you can report.
