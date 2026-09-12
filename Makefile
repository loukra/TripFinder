.PHONY: db db-stop migrate api worker web test lint typecheck stack

# `.env` is where OPENAI_API_KEY and SERPER_API_KEY live (see .env.example).
# Compose reads it on its own; the native processes need it exported for them.
LOAD_ENV = set -a; [ -f .env ] && . ./.env; set +a;

db:
	docker compose up -d postgres

db-stop:
	docker compose stop postgres

# Nothing applies migrations on start-up, deliberately: a process that
# migrates the database it happens to point at is a process that can rewrite
# production by being started with the wrong URL. A fresh clone runs this once.
migrate:
	$(LOAD_ENV) cd backend && uv run alembic upgrade head

api:
	$(LOAD_ENV) cd backend && PYTHONPATH=src uv run uvicorn tripfinder.main:app --reload

worker:
	$(LOAD_ENV) cd backend && PYTHONPATH=src uv run python -m tripfinder.worker

web:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest
	cd frontend && npm run test

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

typecheck:
	cd backend && uv run mypy .
	cd frontend && npm run typecheck

stack:
	docker compose --profile full up
