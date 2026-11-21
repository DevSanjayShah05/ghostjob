# GhostJob: Full Build Spec (Project 1 of 7)

> Saved from Dev's master prompt on 2026-11-20. Most edits only fix formatting: tables, duplicated lines from the
> paste, and broken numbering. Three gaps in the paste were filled in: the Back end and Lever rows, and the Phase 12
> description. They're listed in `docs/DECISIONS.md`, along with proposed changes to the spec. Proposed changes
> don't take effect until Dev approves them.

Workflow: build one phase at a time. At the end of each phase, list what was built, how to run it, and the
acceptance-check results, then stop and wait for "Phase N approved". Commit after every phase.

## 1. Role, product and stack

**Role:** a senior full-stack engineer, data engineer and product designer working with Dev (a data analyst).
The job is to build GhostJob as a production-quality portfolio project that could also become a real startup.
Write clean, typed, tested code, and explain each decision in plain words in the README. The final product must
never use fake data. Mock data is allowed only in Phase 7–8 previews, and it must be clearly labeled.

**Working rules**
- Build only the phase Dev asks for. At the end, list what was built, how to run it, and the acceptance-check
  results, then stop.
- If something in this spec is impossible or a bad idea, say so and suggest a fix. Don't silently change the spec.
- Respect every data source's terms of service and robots.txt. Never scrape LinkedIn or Indeed. Use only public
  ATS APIs and official APIs.
- Keep secrets in .env files and never commit them. Provide a .env.example.

### Product vision
GhostJob tells job seekers which postings are real. Many postings are reposted for months, already filled, or
posted only to collect resumes. GhostJob tracks every posting daily and gives each one a Ghost Score (0–100) with
a plain-English reason. It also shows how well your resume matches the real postings.

One-line pitch: **"Stop applying to ghosts."**

| User | Main need | Key screen |
|---|---|---|
| Job seeker (primary) | Skip fake postings, focus on real ones | Radar dashboard, Job detail |
| Job seeker with resume | Know their fit and missing skills | Resume Match |
| Journalist / analyst | Market trends on ghost hiring | Insights (Ghost Index) |
| Recruiter (future paid tier) | Prove their postings are real | Company profile "Verified" badge |

**In scope:**
- Daily ingestion of about 150–300 companies' public job boards, with posting history
- Ghost Score model with explanations
- LLM vagueness scoring
- Resume matching
- Insights page
- Watchlist and alerts
- Optional Chrome extension

**Out of scope:**
- User payments
- Applying to jobs for the user
- Scraping sites that forbid it

### Tech stack (use exactly this unless a problem is flagged)

| Layer | Tool | Why |
|---|---|---|
| Monorepo | pnpm workspaces: apps/web, apps/api, pipelines/, analytics/, extension/ | One repo, clear folders |
| Front end | Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui | Modern, fast, recruiters recognize it |
| Motion | Framer Motion + GSAP (radar sweep) | Smooth, "crazy" feel |
| Visuals | visx or Recharts for charts, custom SVG/Canvas radar, cmdk command palette | Full control of the look |
| Back end | FastAPI (Python 3.11+), Pydantic, SQLAlchemy | |
| Database | PostgreSQL (Neon or Supabase free tier) + pgvector | Relational and vector search in one place |
| Transformations | dbt-core on Postgres | Shows analytics-engineering skills |
| Scheduling | GitHub Actions cron (daily 06:00 UTC) | Free and simple |
| ML | pandas, scikit-learn, XGBoost, SHAP | Explainable model |
| Embeddings | sentence-transformers all-MiniLM-L6-v2, run locally | Free, no API cost |
| LLM | Provider-agnostic wrapper (Claude or OpenAI via env var), JSON-schema outputs, caching | Swap providers easily |
| Auth | Supabase Auth or Clerk (email magic link) | Watchlist and resumes per user |
| Deploy | Vercel (web), Render or Railway (API), Neon (DB) | Free tiers |
| Quality | pytest, Playwright, ESLint, Prettier, Ruff, mypy, GitHub Actions CI | Looks professional |

## 2. Data sources, schema and pipeline

Core idea: a ghost job can only be spotted over time. So the pipeline takes a daily snapshot of every posting
and keeps its full history.

### Sources (check the current terms and endpoints before coding)

| Source | What we get | Access |
|---|---|---|
| Greenhouse Job Board API | Title, location, description, departments, updated_at, absolute_url | Public, no key: `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` |
| Lever Postings API | Title, location, team, description, createdAt, hostedUrl | Public, no key: `api.lever.co/v0/postings/{company}?mode=json` |
| Ashby Job Board API | Title, location, description, publishedAt, compensation | Public, no key: `api.ashbyhq.com/posting-api/job-board/{name}` |
| Adzuna API | Broad market postings and salary for benchmarks | Free API key |
| USAJobs API | Federal postings (a clean "real job" baseline) | Free API key |
| WARN Act layoff notices | Company layoffs by date and state | Public state data (use a maintained aggregate if available) |
| Company metadata | Industry, size bucket, HQ | Hand-built seed CSV (`seeds/companies.csv`) |

**Seed list:** start with 150 companies that use Greenhouse, Lever or Ashby, spread across tech, finance,
healthcare, retail and consulting. The CSV holds company_name, ats, board_token, industry, size_bucket and
hq_state. Write a validator script that confirms each token returns data.

### Database schema (PostgreSQL)

| Table | Key columns | Notes |
|---|---|---|
| companies | id, name, ats, board_token, industry, size_bucket, hq_state, logo_url | One row per company |
| postings | id, company_id, source_job_id, title, title_normalized, location, remote_type, department, seniority, apply_url, salary_min, salary_max, first_seen_at, last_seen_at, is_active, content_hash | One row per unique posting |
| posting_snapshots | posting_id, snapshot_date, source_updated_at, content_hash, is_present | One row per posting per day: the history |
| posting_text | posting_id, description_clean, word_count, embedding vector(384) | Clean text and pgvector embedding |
| repost_links | posting_id, previous_posting_id, similarity, gap_days | Detects "same job, new ID" reposts |
| layoff_events | company_id, notice_date, employees_affected, state | From WARN data |
| llm_assessments | posting_id, model, vagueness_score, evergreen_flag, red_flags jsonb, prompt_version, created_at | Cached LLM outputs |
| ghost_scores | posting_id, scored_at, score, band, top_reasons jsonb, model_version | Latest score and history |
| users, resumes, matches, watchlist, alerts | Standard user tables | Resume stored as parsed text and an embedding. The raw file is never kept after parsing. |

Add indexes on (company_id, is_active), (snapshot_date) and title_normalized, plus an HNSW index on the embeddings.

### Pipeline (`pipelines/`)
1. **Extract:** one connector class per ATS, all with the same interface: `fetch_jobs(company) -> list[RawJob]`.
   Each has retries with backoff, a polite 1–2 second delay, a timeout and a clear User-Agent.
2. **Load raw:** save the raw JSON to `raw_jobs` (jsonb) with the fetch timestamp, so it can always be re-processed.
3. **Clean:**
   - Strip HTML.
   - Normalize titles ("Sr. Data Analyst II" → "data analyst", seniority = senior).
   - Parse salary ranges.
   - Classify each posting as remote, hybrid or onsite.
4. **Diff:** compare today vs yesterday by source_job_id and content_hash. Update first_seen_at, last_seen_at and
   is_active, and write posting_snapshots.
5. **Repost detection:** for each new posting, find postings from the same company in the last 180 days with the
   same normalized title and cosine similarity ≥ 0.92. If the old posting closed, link the two in repost_links.
6. **dbt models (`analytics/`):** staging → intermediate → marts.
   - Marts: fct_posting_daily, dim_company, mart_ghost_features, mart_company_hiring_trend,
     mart_ghost_index_by_industry.
   - dbt tests: not_null, unique, relationships, accepted_values.
7. **Schedule:** a GitHub Actions workflow runs daily. It logs row counts, new and closed postings, and failures
   to a pipeline_runs table.

**Important:** start the daily pipeline as early as possible (end of Phase 1), because ghost signals need 3–6 weeks
of history. Until then, use the ATS updated_at/createdAt dates as a partial backfill.

## 3. Ghost Score model, LLM layer and resume match

The Ghost Score is an honest estimate, not the truth. Nobody publishes "this job was fake," so there are no true
labels. The model uses weak supervision: clear rules create starter labels, a small hand-labeled set checks those
rules, and a model learns from both. Say this openly in the UI and the README. Interviewers respect it.

### Features (built in dbt `mart_ghost_features`, one row per active posting)

| Feature | Meaning | Ghost direction |
|---|---|---|
| days_open | Days since first seen | Higher = more ghostly |
| repost_count_180d | Times this same job was reposted | Higher |
| date_refresh_count | Times updated_at changed with no real content change | Higher (fake "freshness") |
| similar_open_same_company | Near-duplicate postings open at the same time | Higher |
| company_open_roles_per_size | Open roles vs company size bucket | Very high = suspicious |
| company_layoff_90d | WARN layoff in the last 90 days | Yes = higher |
| company_hiring_trend_30d | Change in the company's open roles | Shrinking + old posting = higher |
| has_salary, salary_range_ratio | Salary shown, and how wide the range is (max/min) | Missing or very wide = higher |
| vagueness_score | LLM score, 0–1 | Higher |
| evergreen_flag | "Always accepting", "talent pool", "future openings" | Yes = much higher |
| description_word_count | Length | Very short or boilerplate = higher |
| boilerplate_similarity | Similarity to the company's other postings | Very high = template spam |
| seniority, remote_type, industry | Context (categorical) | Controls |

### Labels (weak supervision)
- **Likely ghost (1):** open ≥ 60 days AND (reposted ≥ 2 times OR refreshed ≥ 3 times), OR evergreen_flag = true.
- **Likely real (0):** closed within 30 days and never reposted, or a USAJobs posting with a closing date.
- **Unlabeled:** everything else. The model scores these postings but doesn't train on them.
- **Hand-labeled check set:** a small Streamlit labeling tool (`analytics/labeler.py`). Dev labels about 300
  postings by reading them. Report how well the rules agree with Dev's labels (Cohen's kappa).

### Model
1. Time-based split: train on older postings and test on the newest 20%, so nothing leaks from the future.
2. Logistic regression as the baseline and XGBoost as the main model, tuned with 5-fold time-series CV.
3. Metrics: PR-AUC (main), ROC-AUC, precision in the top 10% and a calibration curve. Also evaluate on Dev's
   hand-labeled set.
4. Calibrate the probabilities (isotonic) and scale them to 0–100. Bands: 0–34 Real, 35–64 Suspicious, 65–100 Ghost.
5. Run SHAP for every score and save the top 3 reasons as plain sentences, for example "Reposted 4 times since
   June", "Open for 97 days" or "Company had layoffs 41 days ago".
6. Save the model with a version tag, a model card (`analytics/MODEL_CARD.md`) and a feature-importance plot.
7. Re-score all active postings daily after the pipeline runs.

### LLM layer (`apps/api/llm/`)
- **Vagueness assessment:** send the clean description and get back strict JSON:
  `{vagueness_score 0-1, evergreen_flag bool, red_flags: [string], responsibilities_specific: bool,
  has_team_or_manager_detail: bool, summary: string (max 25 words)}`. Validate it with Pydantic, and retry once
  if it's invalid.
- **Caching:** cache by content_hash + prompt_version, so the same text is never paid for twice. Send only new
  postings, in batches. Set a daily cost cap with an env var.
- **Prompts:** prompt files live in `prompts/` with version numbers. Keep a test set of 20 postings to check that
  a new prompt still works.

### Resume match
1. The user uploads a PDF or DOCX. Parse it to text (pdfplumber / python-docx) and delete the file after parsing.
2. The LLM extracts skills, tools, years of experience and target titles as JSON.
3. Hybrid match score = 60% embedding similarity (resume vs posting) + 40% skill overlap. Required skills count
   double.
4. Output for each job: match %, matched skills, missing skills, and a 2-line tip on how to close the gap.
5. Final ranking = match × (1 − ghost probability). This is the key product idea: the best jobs to apply to are
   real ones you fit.

## 4. API (FastAPI, `apps/api`)

- Every response is typed with Pydantic and documented in the auto-generated OpenAPI at `/docs`.
- The API uses cursor pagination, input validation, rate limiting (slowapi) and CORS for the web domain only.

| Method + path | Purpose | Key params / response |
|---|---|---|
| GET /health | Uptime and last pipeline run | {status, last_run_at, postings_active} |
| GET /stats/overview | Live numbers for the landing page | total tracked, % ghost, companies, new today |
| GET /jobs | Search and filter postings | q, company, industry, band, remote, seniority, min_salary, sort (ghost, newest, match), cursor |
| GET /jobs/{id} | Job detail | posting + score + top_reasons + snapshot timeline + repost chain + LLM red flags |
| GET /jobs/{id}/similar | Real alternatives | 5 similar postings with band = Real |
| GET /companies | Company list | ghost rate, open roles, trend |
| GET /companies/{id} | Company profile | hiring trend series, layoffs, ghost rate history, open roles |
| GET /insights/ghost-index | Market trends | by industry, title, seniority, remote type, posting age, weekday |
| POST /resumes | Upload and parse a resume (auth) | returns skills JSON |
| GET /matches | Ranked jobs for the user's resume (auth) | match %, ghost score, final rank |
| GET/POST/DELETE /watchlist | Save companies or jobs (auth) | — |
| GET /extension/score?url= | Score lookup for the Chrome extension | band, score, top reason |

Write pytest tests for every route against a seeded test database.

## 5. Front end: design system and every screen

**Look and feel:** a dark "signal intelligence" console, like a submarine sonar room crossed with a premium fintech
app. Calm and precise, never cartoonish. Real jobs glow solid. Ghost jobs are see-through and drift slightly, as if
they're not really there.

### Design tokens (`apps/web/styles/tokens.css`)

| Token | Value | Use |
|---|---|---|
| --bg | #06080B | Page background |
| --panel | #0C1117 + 1px border #1A232E | Cards, panels |
| --grid | #11202A | Radar rings, chart grids |
| --text / --muted | #E6EDF3 / #7D8A99 | Text |
| --real | #3DFFA2 (mint) | Real band, success |
| --suspect | #FFC24B (amber) | Suspicious band |
| --ghost | #B48CFF (spectral violet) | Ghost band |
| --accent | #4FD1FF (sonar cyan) | Links, focus, radar sweep |
| Fonts | Space Grotesk (headings), Inter (body), JetBrains Mono (numbers, IDs) | Load with next/font |
| Radius / spacing | 14px cards, 8px controls, 4px spacing scale | Consistent rhythm |

**Accessibility:**
- Every band uses color plus a second cue (an icon and a label), so it still works for color-blind users.
- Check that text contrast meets WCAG AA.
- Support prefers-reduced-motion, which turns off the sweep, drift and parallax.

### Global UI
- **Top bar:**
  - Logo: a small ghost made of radar rings.
  - Search.
  - Nav: Radar, Companies, Insights, Match.
  - A live "pipeline status" dot with the last-run time.
- **Command palette (cmdk), ⌘K / Ctrl+K:** jump to a company, job or page, or type a query like "real data analyst
  remote" to filter.
- **Keyboard shortcuts:**
  - `/` focuses search.
  - `j` / `k` move through jobs.
  - `g` then `r`/`c`/`i`/`m` switches pages.
  - `s` saves to the watchlist.
- **Feedback:** toasts for saves and alerts. Skeleton loaders shaped like the real content, no spinners.

### Screen 1: Landing page (`/`)
1. **Hero:**
   - A full-width radar (Canvas) sweeping slowly. Each blip is a real posting from today's data. Mint blips pulse,
     and violet ghost blips fade in and out as the sweep passes them.
   - Headline: "Stop applying to ghosts."
   - Subline: "We track [N] job postings every day and flag the ones that aren't real."
   - Two buttons: "Scan the market" and "Match my resume".
2. **Live counter strip** (numbers roll up on scroll): postings tracked, % flagged ghost, companies watched, reposts
   caught this week.
3. **"How it works":** 3 steps with scroll-triggered animation: Track daily → Score with AI → Match you to real jobs.
4. **Ghost anatomy:** one real example posting. As you scroll, its red-flag sentences highlight one by one, each
   with its SHAP-reason label.
5. **Ghost Index teaser:** a chart and a link to Insights.
6. **Footer:** methodology, GitHub, and "Built by Dev Shah" linking to the portfolio.

### Screen 2: Radar dashboard (`/radar`), the main screen
- **Left (filters, 280px):** role, location, remote, seniority, industry, salary minimum, band toggle chips (Real /
  Suspicious / Ghost) and a "hide ghosts" switch.
- **Center (radar, about 55%):** the radar shows the filtered postings.
  - Distance from the center = days open. Angle groups = industry. Blip size = salary.
  - Hover shows a mini card, and click opens the detail drawer. A legend sits in the corner.
- **Right (feed):** a virtualized list of job cards.
  - Each card shows the company logo, title, location, salary, Ghost Score pill, match % (if a resume is uploaded)
    and "seen X days".
  - Ghost cards render at 55% opacity with a slow 6px float animation.
- **Top of center:** 4 KPI tiles for the current filter: postings, % real, median days open, median salary.

### Screen 3: Job detail (drawer + full page `/jobs/[id]`)
- **Score dial:** an animated 270° gauge from 0 to 100, colored by band, with the band label underneath.
- **"Why this score":** a horizontal SHAP bar chart in plain English (what pushes toward ghost vs toward real).
- **Life timeline:** a horizontal strip from first seen to today, with markers for each repost, date refresh and
  company layoff.
- **Repost chain:** linked cards for the earlier copies of this posting, with their dates.
- **AI red flags:** the LLM's flags, with the matching sentences highlighted in the description.
- **Resume fit (if a resume is uploaded):** match %, matched skills as mint chips, missing skills as outline chips.
- **"Real alternatives":** 5 similar postings scored Real.
- **Buttons:** Apply (opens the original link), Save, and Share (copies a link with an OG image showing the score).

### Screen 4: Company profile (`/companies/[slug]`)
- **Header:** logo, industry, size, ghost rate badge and a "Hiring heartbeat" sparkline.
- **Hiring heartbeat chart:** open roles over time (line), with layoff events as markers and the ghost share as a
  shaded area.
- **Open roles table:** sortable by ghost score.
- **"Repost hall of fame":** the company's most-reposted roles.

### Screen 5: Resume Match (`/match`)
- **Upload:** a drag-and-drop zone with a scanning-beam animation while the resume parses.
- **Skill constellation:**
  - Your skills appear as glowing nodes.
  - Skills that the top 50 matching real jobs want but you lack appear as dim nodes, sized by demand.
  - Click a node to see the jobs that ask for it.
- **Ranked list:** final rank = match × realness, with filters.
- **"Top 5 skills to learn next":** each with how many more real jobs it would unlock.

### Screen 6: Insights (`/insights`), the analyst story
This page is the data analyst portfolio piece. It reads like a short report with charts, written in plain words.
- Ghost Index by industry (bar chart), by seniority and by remote type.
- "How long until a posting is probably dead?": a survival curve of days open.
- Ghost rate vs company layoffs (scatter).
- Salary transparency vs ghost rate.
- 3–5 written findings with exact numbers and the date range.
- Every chart has a "How we measured this" tooltip.

### Screen 7: Watchlist and alerts (`/watchlist`)
Saved companies and jobs, plus an optional weekly email digest such as "3 new real Data Analyst jobs at your saved
companies."

### Responsive layout and states
- **Mobile:**
  - The radar becomes a compact sweep header.
  - The feed becomes the main view.
  - The filters move into a bottom sheet.
- **States:** every screen gets an empty state, a loading state and an error state. Example empty state: "No ghosts
  here. Every job in this filter looks real."

## 6. Build phases (one at a time, stop after each)

0. **Phase 0: Setup.**
   - Monorepo with pnpm workspaces and a Python env (uv or poetry).
   - Docker Compose with Postgres + pgvector.
   - .env.example, pre-commit hooks, CI running lint + tests, and a README skeleton.
   - *Done when:* `docker compose up` starts the DB, `pnpm dev` shows a blank Next.js page, FastAPI `/health` returns
     OK, and CI is green.
1. **Phase 1: Ingestion.**
   - Seed CSV of 150 companies plus the token validator.
   - Greenhouse, Lever and Ashby connectors.
   - Raw load, cleaning, title normalization, salary parsing and diff logic.
   - posting_snapshots, the pipeline_runs log, and the daily GitHub Actions cron.
   - *Done when:* one run loads 3,000+ postings, a second run correctly marks new and closed postings, unit tests
     cover each connector with saved JSON fixtures, and the cron is live.
2. **Phase 2: dbt models.**
   - The staging, intermediate and mart models from section 2, with tests and docs (`dbt docs generate`).
   - *Done when:* `dbt build` passes with all tests, and a screenshot of the lineage graph is saved to docs/.
3. **Phase 3: EDA + insights notebook.**
   - `analytics/01_eda.ipynb` covers data quality checks, the distribution of days open, repost rates by industry
     and company, salary transparency, and a survival curve (lifelines).
   - Write 5 findings in plain English, with numbers.
   - *Done when:* the notebook runs top to bottom, and docs/FINDINGS.md lists 5 findings with charts.
4. **Phase 4: Embeddings + repost detection.**
   - Generate embeddings, build the HNSW index, and link reposts.
   - *Done when:* precision is checked on 50 sampled repost links (target ≥ 90% correct, as judged by Dev).
5. **Phase 5: LLM layer.**
   - Provider wrapper, versioned prompts, JSON validation, caching, cost cap and the 20-posting prompt test set.
   - *Done when:* all active postings are assessed, a re-run costs $0 (cache hits), and the daily spend log works.
6. **Phase 6: Ghost Score model.**
   - Labeling rules, the Streamlit labeler, features, baseline + XGBoost, time split, calibration, SHAP reasons,
     the model card and the daily scoring job.
   - *Done when:* PR-AUC beats the baseline, the calibration plot is saved, Cohen's kappa vs Dev's labels is
     reported, and every active posting has a score + 3 reasons.
7. **Phase 7: API.**
   - Every route from section 4, with tests and rate limits.
   - *Done when:* pytest passes, and `/docs` shows every route with examples.
8. **Phase 8: Design system + landing page.**
   - Tokens and fonts.
   - Base components: Button, Card, ScorePill, Dial, Chip, KPI tile, Drawer, Toast and Skeleton.
   - The command palette, and the landing page with the live radar.
   - *Done when:* Lighthouse performance is ≥ 90 and accessibility ≥ 95 on the landing page, it works with reduced
     motion, and it looks right at 375px, 768px and 1440px.
9. **Phase 9: Radar dashboard + job detail.**
   - Filters in the URL (shareable), the radar, the virtualized feed, the detail drawer, the full job page and the
     OG share image.
   - *Done when:* filtering 5,000 postings stays smooth (60fps target on the radar), and Playwright tests cover
     search → filter → open job → save.
10. **Phase 10: Companies + insights pages.**
    - The company profile with the hiring heartbeat, and the insights page built from FINDINGS.md.
    - *Done when:* every chart has a source tooltip, and the numbers match the notebook.
11. **Phase 11: Auth + resume match + watchlist.**
    - Login, upload, parsing, the skill constellation, ranked matches, the watchlist and the weekly digest
      (Resend free tier).
    - *Done when:* Dev's own resume returns sensible top matches, the missing skills are correct by Dev's check,
      and the uploaded file is deleted after parsing.
12. **Phase 12 (optional): Chrome extension.**
    - Manifest V3. On supported job pages, show a badge with the Ghost Score.
    - *Done when:* the badge appears on 3 test pages and fails quietly when there's no score.
13. **Phase 13: Ship it.**
    - Deploy (Vercel + Render/Railway + Neon) to the custom subdomain ghostjob.devsanjayshah.me.
    - Error tracking (Sentry free tier) and basic analytics (Plausible or Vercel Analytics).
    - Final README and a 90-second demo video.
    - *Done when:* the live URL works on phone and laptop, the pipeline has run unattended for 7 days, and the
      README is complete.

## 7. Testing, README and portfolio story

### Testing checklist
- **Python:** pytest for the connectors (saved fixtures), cleaning functions, diff logic, feature math and API
  routes. Target ≥ 80% coverage on pipelines/ and apps/api/.
- **dbt:** schema tests on every mart.
- **Web:** Playwright end-to-end tests for the 4 main flows, and Vitest for utility functions.
- **Data quality alerts:** if a run loads 50% fewer postings than the 7-day average, mark the run as failed and
  open a GitHub issue automatically.

### README structure (written in simple language)
1. A hero GIF of the radar, the live link and the one-line pitch.
2. The problem in 3 sentences, with one real number from the data.
3. Key findings: the top 3 from FINDINGS.md.
4. How it works: an architecture diagram (sources → pipeline → Postgres/dbt → model + LLM → API → web/extension).
5. How the Ghost Score works, plus its limits: no true labels, weak supervision, and what it can get wrong.
6. Tech stack table.
7. Run it locally in 5 commands.
8. Data ethics: only public ATS APIs, robots.txt respected, resumes deleted after parsing.
9. Roadmap and startup angle: a recruiter "Verified Real" badge, paid alerts, B2B market reports.

### Resume bullets (fill in real numbers at the end)
- Built GhostJob, a full-stack AI platform that tracks [N] job postings from [N] companies daily and flags likely
  "ghost jobs" with an explainable XGBoost model (PR-AUC [X]).
- Designed a daily ELT pipeline (Python, PostgreSQL, dbt, GitHub Actions) with snapshot history, repost detection
  using vector embeddings, and automated data-quality checks.
- Used an LLM with validated JSON outputs and caching to score posting vagueness for under $[X]/day, and found
  that [key finding, e.g. postings without salary were X% more likely to be ghosts].

### 30-second interview story
"While job hunting, I kept applying to jobs that never replied, so I built GhostJob. It checks about [N] company
job boards every day and saves the history of each posting. If a job keeps getting reposted, stays open for months,
or the company just had layoffs, the score goes up. There are no true labels for fake jobs, so I made starter labels
with clear rules, checked them against 300 jobs I labeled myself, and trained an XGBoost model with SHAP so every
score has a reason. My biggest finding was [finding]. It's live at ghostjob.devsanjayshah.me."
