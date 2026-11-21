# GhostJob

**Stop applying to ghosts.** GhostJob checks public company job boards every day, keeps the history of each
posting, and gives each one a Ghost Score (0–100) with a plain-English reason. A posting gets a high score if it
keeps getting reposted, stays open for months, or comes from a company that just had layoffs.

> 🚧 Work in progress. The build plan is in [`GHOSTJOB_SPEC.md`](GHOSTJOB_SPEC.md) and the decision log is in
> [`docs/DECISIONS.md`](docs/DECISIONS.md).

| Phase | What | Status |
|---|---|---|
| 0 | Setup: monorepo, Postgres + pgvector, CI | ✅ |
| 1 | Daily ingestion from Greenhouse / Lever / Ashby | ⏳ |
| 2 | dbt models | |
| 3 | EDA + findings | |
| 4 | Embeddings + repost detection | |
| 5 | LLM vagueness scoring | |
| 6 | Ghost Score model (weak supervision + XGBoost + SHAP) | |
| 7 | API | |
| 8–11 | Web app: landing, radar, job detail, companies, insights, resume match | |
| 12 | Chrome extension (optional) | |
| 13 | Ship it | |

## How it's organized

```
apps/web      Next.js front end (TypeScript, Tailwind)
apps/api      FastAPI back end (ghostjob_api package)
pipelines/    daily ingestion jobs (Phase 1)
analytics/    dbt models, EDA notebook, Ghost Score model (Phases 2–6)
extension/    Chrome extension (Phase 12)
db/init/      SQL that runs when the local database is first created (enables pgvector)
```

## Run it locally

You need Docker, Node 20+, and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
make setup      # Python + JS dependencies, git hooks
make db         # Postgres 16 + pgvector in Docker
make api        # http://localhost:8000/health  (API docs at /docs)
make web        # http://localhost:3000
```

`make test` runs the Python tests and `make lint` runs every linter and type checker.

## Data ethics

GhostJob uses only public ATS job-board APIs and official APIs. It respects robots.txt and never scrapes LinkedIn
or Indeed. Uploaded resumes are deleted as soon as they're parsed.

## License

MIT
