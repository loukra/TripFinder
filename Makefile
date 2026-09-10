.PHONY: db db-stop api worker web test lint typecheck stack

db:
	docker compose up -d postgres

db-stop:
	docker compose stop postgres

# `.env` is where OPENAI_API_KEY lives (see .env.example). Compose reads it
# on its own; the native processes need it exported for them.
LOAD_ENV = set -a; [ -f .env ] && . ./.env; set +a;

api:
	$(LOAD_ENV) cd backend && PYTHONPATH=src uv run uvicorn tripfinder.main:app --reload

worker:
	$(LOAD_ENV) cd backend && PYTHONPATH=src uv run python -m tripfinder.worker

web:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

typecheck:
	cd backend && uv run mypy .
	cd frontend && npm run typecheck

stack:
	docker compose --profile full up
