.PHONY: setup db db-down api web test lint ingest validate-seeds dbt dbt-docs eda

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

dbt:        ## build all dbt models and run their tests
	uv run python analytics/run_dbt.py build

dbt-docs:   ## generate and open the dbt docs site (lineage graph included)
	uv run python analytics/run_dbt.py docs generate --static && open analytics/target/static_index.html

eda:        ## re-run the EDA notebook top to bottom (set DATABASE_URL to point it at Neon)
	cd analytics && uv run jupyter nbconvert --to notebook --execute --inplace 01_eda.ipynb
