.PHONY: setup db db-down api web test lint

setup:      ## install Python + JS dependencies and git hooks
	uv sync
	pnpm install
	uv run pre-commit install

db:         ## start Postgres + pgvector
	docker compose up -d --wait

db-down:
	docker compose down

api:        ## FastAPI on :8000 (docs at /docs)
	uv run uvicorn ghostjob_api.main:app --app-dir apps/api --reload

web:        ## Next.js on :3000
	pnpm dev

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy
	pnpm lint && pnpm typecheck
