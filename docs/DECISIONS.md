# Decisions and spec notes

The spec says: if something is impossible or a bad idea, say so and suggest a fix, and don't change it silently.
This file records those notes. Proposals marked **open** need Dev's OK before they change anything.

## Gaps in the pasted spec, filled in (Phase 0)

| Gap | What I filled in |
|---|---|
| The stack table had no Back end row, but section 4 is all FastAPI | FastAPI (Python 3.11+), Pydantic, SQLAlchemy |
| Phase 1 and the seed list mention Lever, but the sources table had no Lever row | Lever's public postings API, `api.lever.co/v0/postings/{company}?mode=json` |
| The Phase 12 text was cut off after "Manifest V3. On" | "On supported job pages, show a badge with the Ghost Score" |

## Phase 0 choices

- **uv, not poetry**, for Python. It's faster and has a single lockfile (`uv.lock`). There is one Python environment
  at the repo root, shared by `apps/api`, `pipelines` and `analytics`, so cross-package imports just work.
- **pnpm 10 pinned** through `packageManager`. pnpm 12 failed to install through corepack on this machine.
- **Next.js 15 + Tailwind v4.** shadcn/ui gets added in Phase 8, when the components are built.
- **`/health` returns `status: "ok"` even when the database is down.** It reports whether the API process is up,
  and the database state is a separate field (`db: ok | unavailable`). That way a DB outage doesn't make the host
  restart a healthy API.
- **CI has a `db` job** that runs `docker compose up --wait` and checks that the pgvector extension exists. This is
  how the "docker compose up starts the DB" check is proven on every push.

## Proposals (open)

1. **Label leakage in the Ghost Score model (Phase 6). This one matters most.**
   - The weak-label rules are built from `days_open`, `repost_count_180d`, `date_refresh_count` and
     `evergreen_flag`, and those same columns are model features.
   - XGBoost will just relearn the rules, and PR-AUC against rule labels will look near-perfect while meaning
     very little.
   - Fix:
     - Report the rule-label PR-AUC only as a sanity check.
     - Make **Dev's ~300 hand labels the headline evaluation**.
     - Also train a variant **without** the label-defining features, to show what the other signals add.
     - Say all of this in the model card.
2. **"Likely real = closed within 30 days" mixes in future information.** A posting's label depends on what
   happens after it's scored. The time-based split helps, but the newest postings can't have this label yet. Fix:
   only label postings whose outcome window has fully passed (first seen ≥ 30 days before the cutoff).
3. **Add an `ollama` LLM provider next to Claude and OpenAI (Phase 5).** A local model makes development and the
   20-posting prompt tests free. The paid provider is used only for the production batch, under the cost cap.
4. **WARN data comes state by state, in messy formats.** Plan for a few large states (CA, NY, TX, WA) plus fuzzy
   matching of company names, and report the match rate. Don't promise national coverage.
5. **Only 3–6 weeks of history at the start.** Phase 3 findings drafted early will be thin. Write them, but date
   every finding and refresh them before Phase 10.
