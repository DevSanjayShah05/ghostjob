.PHONY: setup db db-down api web test lint ingest validate-seeds

setup:      ## install Python + JS dependencies and git hooks
	uv sync
	pnpm install
	uv run pre-commit install

db:         ## start Postgres + pgvector
	docker compose up -d --wait

db-down:
	docker compose down

api:        ## FastAPI on http://127.0.0.1:8000 (docs at /docs)
	uv run uvicorn ghostjob_api.main:app --app-dir apps/api --reload

web:        ## Next.js on :3000
	pnpm dev

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy
	pnpm lint && pnpm typecheck

ingest:     ## run the daily pipeline once against DATABASE_URL (local DB by default)
	PYTHONPATH=pipelines uv run python -m ghostjob_pipelines.run

validate-seeds:  ## check every board token in seeds/companies.csv returns jobs
	PYTHONPATH=pipelines uv run python -m ghostjob_pipelines.validate_seeds
