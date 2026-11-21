# Decisions and spec notes

The spec says: if something is impossible or a bad idea, say so and suggest a fix, and don't change it silently.
This file records those notes. A proposal changes nothing until Dev approves it.

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

## Proposals (approved by Dev, 2026-11-20)

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

## Phase 1 choices

- **The seed list was built by probing, not guessing.**
  - Round 1 checked 262 hand-picked candidates: 143 boards worked. Many companies have switched ATS or use Workday.
  - Round 2 tried other board IDs on all three ATSs, plus about 60 new retail and consulting candidates: 70 more
    boards worked.
  - Generic IDs (mercury, fetch, alloy, cortex…) were checked against the company name in the API response and in
    the description text. That caught two wrong matches: `fetch` is Fetch Pet Insurance, not Fetch Rewards, and
    `pivotal` is a UK nonprofit, so it was dropped.
  - Result: **208 companies**: tech 87, healthcare 36, finance 35, retail 35, consulting 15. By ATS: Greenhouse 134,
    Ashby 55, Lever 19.
  - Large consulting firms mostly use Workday, which we don't scrape, so consulting stays the smallest group.
- **industry, size_bucket and hq_state are hand-assigned estimates**, good for grouping but not authoritative.
- **Storage is designed for Neon's free 0.5 GB tier.** The first full load was 336 MB, which is too close to the
  limit, so three changes were made:
  - **Raw JSON is stored only when a posting is new or its content changed**, not every day. A daily full copy
    is about 27k postings × ~10 KB.
  - **Raw JSON is zlib-compressed into a `bytea` column** (`payload_gz`) instead of `jsonb`. It's 3.3× smaller,
    against about 2× for Postgres's built-in compression. The cost: you can't query raw JSON in SQL. Re-processing
    happens in Python anyway, through `load.decode_payload()`. *This deviates from the spec's "raw_jobs (jsonb)".*
  - **`posting_snapshots` stores `content_hash` and `source_updated_at` only on the day they change**, and NULL
    otherwise. A row is about 45 bytes instead of about 130. Nothing is lost: a date refresh with no content
    change is `source_updated_at IS NOT NULL AND content_hash IS NULL`, which is exactly the
    `date_refresh_count` feature in Phase 6.
- **"Closed" means "missing from a board we fetched successfully."**
  - When a board errors, that day becomes a gap for the company, not a closure of all its postings.
  - When a board that had at least 5 active postings suddenly returns 0, it's marked `suspect_empty` and closes
    nothing.
- **first_seen_at is when GhostJob first saw a posting.** The ATS's own publish date is kept separately in
  `source_created_at` (Greenhouse first_published, Lever createdAt, Ashby publishedAt). It serves as the partial
  backfill for days open until our own history is long enough.
- **Salary:**
  - Greenhouse ranges don't say whether they're hourly. Values under 300 are annualized ×2,080. In major
    currencies, anything still under 10k a year (for example $750 placeholders or $0) is dropped. No salary is
    better than a wrong one.
  - Structured data comes first: Greenhouse `pay_input_ranges` (the USD range is preferred when there are several),
    Ashby compensation, and Lever `salaryRange`.
  - Otherwise the salary is parsed from the description text.
  - Hourly pay is annualized at 2,080 hours.
  - Numbers that don't look like pay, such as funding rounds, are ignored.
- **remote_type is `unknown` unless the ATS or the location says so.** Most Greenhouse boards list only a city.
  Guessing "onsite" from that would make the remote analysis wrong.
- **Data-quality rule (spec section 7):**
  - A run is `failed` if it sees fewer than 50% of the average postings of the last 7 good runs, or if more than
    20% of boards error.
  - It's `partial` if a few boards error.
  - A failed run exits with code 2, and the workflow opens a GitHub issue.
- **Politeness:**
  - 1.5 s between requests to each API. Lever's robots.txt asks for 1 s.
  - A `GhostJobBot` User-Agent with the repo link.
  - 3 retries with exponential backoff, and only on 429/5xx errors.

## Hosting the database (Phase 1)

- **Neon Free.** Since October 2026 it gives 1 GB per project, needs no card and supports pgvector.
- **Measured after the first full load:** 282 MB.
  - raw_jobs: 130 MB
  - posting_text: 117 MB
  - postings: 19 MB
  - snapshots: 7 MB
- **Expected growth:** about 1,000 new postings a day, each with text and raw JSON, plus about 2 MB of snapshot
  rows. That's roughly 10 MB a day.
- **Phase 4 embeddings** will add about 50–90 MB.
- **Plan:**
  - Before the database passes about 800 MB, add a retention job. For postings closed more than 30 days ago, it
    drops `raw_jobs` and `description_clean` and keeps the posting row, its snapshots and its embedding. Repost
    detection needs only the embedding.
  - If that's not enough, Neon's Launch plan is usage-priced, at roughly $0.35 per GB-month for storage, so a few
    GB costs a few dollars.
