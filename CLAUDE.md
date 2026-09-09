# TripFinder — working agreement

## The two documents

| File | Role | Authority |
|---|---|---|
| `PROJECT.md` | Product & architecture brief — the **why** | Principles, intent, constraints |
| `implementation-plan.md` | Executable brief — the **what** | **Wins on any conflict** |

Read both before starting work. `implementation-plan.md` §0 states the precedence rule.

### PROJECT.md sections that are superseded — do not implement as written

- **§11** — says build a Reddit API adapter. The MVP source is **Arctic Shift** (plan §8).
- **§12** — pipeline order. Use plan **§4.6**, which merges three steps, adds Document Triage,
  and adds the clarification branch.
- **§27** — phase list. Use plan **§10**, which adds the Phase 3.5 walking skeleton.
- **§19/§24** — the percentage and "distribution chart". Use plan **§4**: counts lead, bars only,
  never a pie.
- **§31** — "evaluate technologies later". All decided in plan **§1**.

## How to work

1. **One phase at a time.** Never start the next phase, and never scaffold ahead.
2. Finish to the Definition of Done (plan §12): tests written and passing, lint and typecheck
   clean, failure cases covered, acceptance criteria demonstrably met.
3. Report using the plan §12 template, then **stop and wait**.
4. If the plan looks wrong while implementing it, say so and propose an amendment.
   Do not deviate silently.

## Non-negotiables

- **Plan §0.1** — a failure must never masquerade as a finding. Any step that can drop, exclude, or
  fail to retrieve evidence records what it suppressed and why, exposes it through the API, and has
  a test proving a suppressed run is distinguishable from a genuinely thin one.
- **No LLM decides the final ranking.** Steps 9-12 are deterministic (plan §4.6).
- `domain/` and `ranking/` import nothing from `sources/`, `ai/`, `persistence/`, `api/`, or any
  framework. Enforced by a test (plan §3.1).
- No live LLM or network calls in the normal test suite. Evaluation tests are marked and excluded
  from CI (plan §9).
- Model IDs live in config, never in the domain layer.
- Secrets never enter source control.

## Stack

Python 3.12.14 (via `uv`, pinned in `.python-version`) · FastAPI · Pydantic v2 · SQLAlchemy 2 + Alembic · PostgreSQL 16 · OpenAI behind an
`LLMProvider` port · Next.js + TypeScript frontend · pytest / Vitest / Playwright · ruff + mypy
(strict).

## Commands

Populated during Phase 0. Expected: `make test`, `make lint`, `make typecheck`, `docker compose up`.

Use `uv` for all Python work (`uv sync`, `uv run pytest`) — never bare `pip`, `python`, or `python3`.

**Expected, not a bug:** this machine has pyenv installed, and pyenv also reads `.python-version`.
Because 3.12.14 is managed by uv rather than pyenv, any bare `python3` call in this repo fails with
`pyenv: version '3.12.14' is not installed`. That is the correct outcome — it fails loudly instead of
silently building against the system Python 3.9.8. Do not "fix" it by editing `.python-version`,
installing pyenv Pythons, or lowering the required version. Route every command through `uv run`, and
make the Makefile do the same.
