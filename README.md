# GhostJob

[![CI](https://github.com/DevSanjayShah05/ghostjob/actions/workflows/ci.yml/badge.svg)](https://github.com/DevSanjayShah05/ghostjob/actions/workflows/ci.yml)

**Stop applying to ghosts.** GhostJob checks public company job boards every day, keeps the history of each
posting, and gives each one a Ghost Score (0–100) with a plain-English reason. A posting gets a high score if it
keeps getting reposted, stays open for months, or comes from a company that just had layoffs.

> 🚧 Work in progress. The build plan is in [`GHOSTJOB_SPEC.md`](GHOSTJOB_SPEC.md) and the decision log is in
> [`docs/DECISIONS.md`](docs/DECISIONS.md).

| Phase | What | Status |
|---|---|---|
| 0 | Setup: monorepo, Postgres + pgvector, CI | ✅ |
| 1 | Daily ingestion from Greenhouse / Lever / Ashby | ✅ |
| | *208 companies, 27,412 postings on the first run (2026-11-21)* | |
| 2 | dbt models: staging → intermediate → marts, 80 data tests ([lineage](docs/dbt_lineage.png)) | ✅ |
| 3 | EDA notebook + [5 findings](docs/FINDINGS.md) | ✅ |
| 4 | Embeddings + repost detection | ⏳ |
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

## The daily pipeline

Every day at 06:00 UTC, a GitHub Actions job ([`ingest.yml`](.github/workflows/ingest.yml)) takes a snapshot of
208 company job boards:

1. **Fetch.** One connector per ATS (Greenhouse, Lever, Ashby), all with the same `fetch_jobs(company)` method.
   Public APIs only, 1.5 s between requests, retries with backoff and a clear User-Agent.
2. **Clean.**
   - HTML becomes plain text.
   - Titles are normalized ("Sr. Data Analyst II" → "data analyst") and given a seniority level.
   - Salaries are parsed, with hourly pay annualized.
   - Each posting is classified remote, hybrid, onsite or unknown.
3. **Diff against yesterday.**
   - New postings get a `first_seen_at`.
   - Missing postings are closed.
   - Postings that come back are counted as reopened.
   - Every posting gets one small `posting_snapshots` row per day. That history is how a ghost job gets spotted.
4. **Check quality.**
   - If fewer than 50% of the usual postings show up, or more than 20% of boards fail, the run fails and opens a
     GitHub issue.
   - A board that suddenly returns zero jobs closes nothing.

The company list is [`seeds/companies.csv`](seeds/companies.csv). Every board ID in it was checked with
`make validate-seeds`. The design choices and their trade-offs are in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Run it locally

You need Docker, Node 20+, and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
make setup      # Python + JS dependencies, git hooks
make db         # Postgres 16 + pgvector in Docker
make api        # http://127.0.0.1:8000/health  (API docs at /docs)
make web        # http://localhost:3000
```

`make ingest` runs the pipeline once against your local database. It takes about 7 minutes for all 208
companies. `make test` runs the Python tests (they need `make db` for the database tests), and `make lint` runs
every linter and type checker.

## Data ethics

GhostJob uses only public ATS job-board APIs and official APIs. It respects robots.txt and never scrapes LinkedIn
or Indeed. Uploaded resumes are deleted as soon as they're parsed.

## License

MIT
