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

## Starting a phase

When asked to implement a phase — `/phase 4`, "Phase 4", or "implement the next phase" — follow
this procedure exactly. It is the same every time; only the number changes.

**Before writing any code**

0. `git checkout main && git pull`. If the previous phase's PR is merged or closed, delete its
   branch, local and remote (`git branch -d <branch>`, `git push origin --delete <branch>`).
1. Read the phase's row in plan §10 — its dependencies and its deliverables.
2. Read its acceptance criteria, in the numbered notes below that table.
3. Re-read plan §0.1 (standing principle), §3.1 (layout + import rule), §3.2 (commands),
   §4.6 (pipeline order).
4. If the phase includes an AI step, also read §5 (analysis contract) and §4.7 (triage).
5. Confirm every phase it depends on is merged. If one is not, say so and stop.

**While building**

- Work on a branch named `phase-<n>-<short-slug>`.
- Smallest useful increment, with tests alongside it (`PROJECT.md` §26).
- **Never** scaffold, stub, or "prepare for" a later phase.
- All Python through `uv run`.
- If the plan looks wrong, stop and propose an amendment. Do not deviate silently.

**Before reporting**

- Run `make lint`, `make typecheck`, `make test`. Paste the real output — never assert a pass you
  did not observe.
- Walk each acceptance criterion and state explicitly how it is met.
- Report using the plan §12 template.
- **Push the branch and open a PR against `main`** (`git push -u origin <branch>` then
  `gh pr create`). This happens automatically at the end of every phase — no need to ask.
- **Then stop and wait.** Do not merge the PR, and do not begin the next phase.

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

Populated during Phase 0. **Postgres runs in Docker; backend, worker and frontend run natively** —
hot reload where you edit, hermetic Postgres for tests (plan §3.2).

| Command | Does |
|---|---|
| `make db` / `make db-stop` | Postgres in Docker |
| `make api` · `make worker` · `make web` | The three native processes |
| `make test` · `make lint` · `make typecheck` | Verification |
| `make stack` | Everything containerised (`--profile full`) |

Typical session: `make db` once, then `make api`, `make worker`, `make web` in separate terminals.
Do not containerise the backend or frontend for day-to-day work.

Use `uv` for all Python work — `uv sync` to install, `uv run pytest` to run. It owns the
interpreter, the venv, and the lockfile.

**Python setup (already done, don't re-derive it).** Python 3.12.14 is installed and managed by
**uv**, and pinned in `.python-version`. This machine also has **pyenv**, which reads the same file,
so uv's interpreter is symlinked into pyenv's version directory:

```
~/.pyenv/versions/3.12.14 -> ~/.local/share/uv/python/cpython-3.12-macos-aarch64-none
```

Both tools therefore resolve the same interpreter, and `python`, `python3`, `pip`, and `uv run` all
give 3.12.14 inside this repo while other projects keep their own versions. There is one copy of
Python, not two.

If `python3` ever reports `pyenv: version '3.12.14' is not installed`, the symlink has gone stale
(usually because uv upgraded its managed Python). Recreate it:

```bash
ln -sfn "$(dirname "$(dirname "$(uv python find 3.12)")")" ~/.pyenv/versions/3.12.14 && pyenv rehash
```

Do not respond to that error by editing `.python-version`, lowering the required version, or
installing a second Python through pyenv.
