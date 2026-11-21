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

## Phase 2 choices

- **`fct_posting_daily` is a view, not a table.** It grows by about 27k rows a day. Storing it would spend the free
  database's 1 GB on a cheap join over `posting_snapshots`. The other marts are small tables.
- **`similar_open_same_company` uses an exact match until Phase 4:** same company plus same normalized title.
  On day one, 70% of active postings have at least one such twin, mostly the same role posted in several cities.
  That makes it a weak signal for now. Phase 4 replaces it with embedding similarity, which can also tell a true
  copy from a multi-city posting.
- **The Ghost Index uses transparent rules until the Phase 6 model exists:**
  - `stale_share`: open at least 60 days.
  - `rule_flag_share`: stale AND (refreshed ≥ 3 times OR reopened ≥ 2 times).
  - `rule_flag_share` is 0 at first by construction, because refresh and repost history takes weeks to build.
- **Days open is backfilled with the ATS publish date.** On day one, 99.8% of postings are older than our first
  sighting. The backfill trusts the ATS date, but some ATSs reset that date on a repost. That makes ages look
  *younger*, so the measured staleness is a lower bound.

## Phase 3 choices

- **Correction to Phase 2: the ATS-date backfill can also make ages look *older*.** Lever's `createdAt` is when
  the posting record was made, and companies keep one Lever posting open for years. 42% of Lever postings are
  over a year old, compared with 4–7% on Greenhouse and Ashby. So the "lower bound" note above holds for
  Greenhouse and Ashby, but not for Lever. The healthcare/retail "stalest" signal from Phase 2 came from Lever
  boards. Headline age numbers in FINDINGS.md use Greenhouse + Ashby only. **For Phase 6:** age features will
  be relative to the ATS (a percentile within the ATS), then switch to `first_seen_at` once there are ~60 days
  of history.
- **Repost signal available before Phase 4:** Greenhouse's `internal_job_id` (requisition). A requisition whose live
  posts were published 30+ days apart counts as re-published. Same-day posts of one requisition are multi-city
  copies, not reposts. Read from `raw_jobs` for now. If Phase 6 uses it, it gets promoted to a `postings` column.
- **`updated_at` bulk-touch:** at 19% of Greenhouse companies, 80%+ of postings share one `updated_at` day. Phase 6
  will only count a refresh that is specific to that posting (it shouldn't coincide with most of the board).
- **Survival curve:** Kaplan-Meier with censoring and late entry (`entry` = age when first seen), Lever excluded.
  After one day it can't be fitted (7 closures, and almost no young postings at risk), so the notebook says so
  instead of plotting a misleading curve. It will be re-run after ~30 daily snapshots.
- **The notebook is run against Neon** (the production DB, which has the daily history) via
  `DATABASE_URL=... make eda`. The Neon URL lives only in the local `.env` (gitignored) and the GitHub secret.
- **Salary sanity:** `sanitize_salary` now also drops major-currency amounts over 2M (one USD posting had two numbers
  run together). Non-major currencies (INR, KRW, …) legitimately exceed 2M.
- **Pay-law grouping** is a simple text match on the location string (state codes plus common city names). It's
  good enough for a share-of-postings comparison, but not for labeling individual postings.

## Phase 4 choices

- **Company boilerplate is removed before embedding.** MiniLM reads only the first 256 tokens, and many companies
  open every description with the same "About us" block. At Gopuff and Anduril, 52–62% of description words are
  lines shared across the company's postings. Without stripping, every posting at those companies looks
  near-identical, which would mean false repost links. A line is boilerplate if it appears in ≥ 30% (and ≥ 3) of
  the company's open postings. The remaining text is embedded in up to 4 chunks of ~180 words (the title leads
  the first chunk), and the chunk vectors are averaged.
- **Two link types.** The spec's rule (old posting *closed*, a near-identical one appears within 180 days) can only
  fire as closures accumulate. After one day there are 7 closures, so it can't produce 50 links to check for
  weeks. Added `republished_while_open`: the old copy is still open, the new one is at the *same location*, and it
  was published 30+ days later. Same-day multi-city copies are excluded by the location + gap rules. Both types
  share the spec's candidate filter: same company, same normalized title, cosine ≥ 0.92. The precision check
  samples both types (at least 10 of each).
- **Candidates share the same *title*, not just the same normalized title (stricter than the spec).** The first run
  grouped by `title_normalized` and produced 1,299 links. Reading a sample showed many were different jobs from a
  shared company template: "Senior Buyer, Connected Warfare" vs "Buyer, Autonomous Airpower" (both normalize to
  "buyer"), and "Engineering Manager" vs "Engineering Manager - Realtime". The repost check now groups by
  `title_key`: lowercased, punctuation removed, seniority and team kept. That gives 164 links (165 on Neon). A hand
  read of 10 found 9 that were clearly the same job. The 10th had a vague location ("Hybrid"), and the 50-link check
  decides how much that matters.
- **Greenhouse requisition IDs are not an answer key.** Even exact-title links with ≥ 0.98 similarity share an
  `internal_job_id` only 24% of the time. Companies open a new requisition for the same ad. So the precision
  check relies on Dev's judgment, as the spec says.
- **Chains, not all pairs.** Each posting links to its most recent qualifying predecessor (A ← B ← C).
  `repost_count_180d` follows the chain back in dbt (`int_repost_chain`). Links are kept once found, because they
  record history.
- **`similar_open_same_company` is now embedding-based** (cosine ≥ 0.92, any title). Copies published within a day
  of each other are excluded, because those are multi-city batches, not duplicates. This replaces the Phase 2
  exact-title proxy, where 70% of postings had a "twin".
- **`boilerplate_similarity`** = cosine between a posting and the average of the company's other open postings
  (boilerplate already removed, so a high value means the role text itself is templated). NULL under 5 open
  postings. Both stats are recomputed daily in `posting_similarity`.
- **Candidates are compared exactly, not through HNSW.** Grouping by company + title gives small groups, so an
  exact comparison is fast and has no recall loss. The HNSW index (from Phase 0) serves "similar jobs"
  lookups in the API later.
- **CPU-only PyTorch on Linux** via a uv index pin, so CI and the daily job don't download ~2 GB of CUDA wheels.
  The model is cached between daily runs.
- **The Neon backfill reused the local embeddings**, copied where (company, job id, content hash) match, instead
  of recomputing ~27k postings on a small hosted instance. The daily job embeds the rest.

## Open item: WARN layoff data has no phase (flagged, not yet scheduled)

The spec lists WARN layoff notices as a source and `company_layoff_90d` as a feature, but no build phase ingests
them. Proposal: add a small WARN loader for CA, NY, TX and WA (approved proposal 4) at the start of Phase 4,
before the model needs it in Phase 6. **Needs Dev's OK.**
