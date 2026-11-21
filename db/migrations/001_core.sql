-- Phase 1: companies, raw payloads, postings and their daily history, run logs.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE companies (
    id           serial PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    ats          text NOT NULL CHECK (ats IN ('greenhouse', 'lever', 'ashby')),
    board_token  text NOT NULL,
    industry     text NOT NULL,
    size_bucket  text NOT NULL,
    hq_state     text,
    logo_url     text,
    is_tracked   boolean NOT NULL DEFAULT true,   -- false once removed from seeds/companies.csv
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ats, board_token)
);

CREATE TABLE pipeline_runs (
    id                 serial PRIMARY KEY,
    run_date           date NOT NULL,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,
    status             text NOT NULL DEFAULT 'running'
                       CHECK (status IN ('running', 'success', 'partial', 'failed')),
    companies_total    int,
    companies_ok       int,
    companies_failed   int,
    postings_seen      int,
    postings_new       int,
    postings_closed    int,
    postings_reopened  int,
    postings_changed   int,
    quality_notes      text,
    trigger            text   -- 'cron', 'manual', 'test'
);

-- One row per company per run, so a failing board is easy to spot.
CREATE TABLE company_fetches (
    run_id       int NOT NULL REFERENCES pipeline_runs (id) ON DELETE CASCADE,
    company_id   int NOT NULL REFERENCES companies (id),
    status       text NOT NULL CHECK (status IN ('ok', 'error', 'suspect_empty')),
    jobs_found   int NOT NULL DEFAULT 0,
    duration_ms  int,
    error        text,
    PRIMARY KEY (run_id, company_id)
);

-- Raw ATS JSON, zlib-compressed (about 3x smaller than jsonb's built-in compression).
-- Stored only when a posting is new or its content changed, not every day, to save space.
-- Read it back with ghostjob_pipelines.load.decode_payload().
CREATE TABLE raw_jobs (
    id             bigserial PRIMARY KEY,
    run_id         int NOT NULL REFERENCES pipeline_runs (id) ON DELETE CASCADE,
    company_id     int NOT NULL REFERENCES companies (id),
    source_job_id  text NOT NULL,
    content_hash   text NOT NULL,
    fetched_at     timestamptz NOT NULL DEFAULT now(),
    payload_gz     bytea NOT NULL,
    payload_bytes  int NOT NULL    -- uncompressed size
);
CREATE INDEX raw_jobs_lookup ON raw_jobs (company_id, source_job_id);

CREATE TABLE postings (
    id                 bigserial PRIMARY KEY,
    company_id         int NOT NULL REFERENCES companies (id),
    source_job_id      text NOT NULL,
    title              text NOT NULL,
    title_normalized   text NOT NULL,
    location           text,
    remote_type        text NOT NULL CHECK (remote_type IN ('remote', 'hybrid', 'onsite', 'unknown')),
    department         text,
    seniority          text NOT NULL,
    employment_type    text,
    apply_url          text,
    salary_min         numeric(12, 2),
    salary_max         numeric(12, 2),
    salary_currency    text,
    salary_source      text CHECK (salary_source IN ('structured', 'text')),
    source_created_at  timestamptz,   -- when the ATS says it was first published (partial backfill)
    source_updated_at  timestamptz,   -- the ATS's own "updated" stamp (Greenhouse only)
    first_seen_at      timestamptz NOT NULL,
    last_seen_at       timestamptz NOT NULL,
    closed_at          timestamptz,
    is_active          boolean NOT NULL DEFAULT true,
    times_reopened     int NOT NULL DEFAULT 0,
    content_hash       text NOT NULL,
    UNIQUE (company_id, source_job_id)
);
CREATE INDEX postings_company_active ON postings (company_id, is_active);
CREATE INDEX postings_title_norm ON postings (title_normalized);

-- The history: one row per posting per day it was tracked.
-- To keep rows small, content_hash and source_updated_at are filled in only on the day they change
-- (NULL means "same as before"). So a date refresh with no real edit is:
--   source_updated_at IS NOT NULL AND content_hash IS NULL.
CREATE TABLE posting_snapshots (
    posting_id         bigint NOT NULL REFERENCES postings (id) ON DELETE CASCADE,
    snapshot_date      date NOT NULL,
    run_id             int NOT NULL REFERENCES pipeline_runs (id) ON DELETE CASCADE,
    source_updated_at  timestamptz,   -- set only when the ATS's updated stamp changed
    content_hash       text,          -- set only when the posting is new or its content changed
    is_present         boolean NOT NULL,
    PRIMARY KEY (posting_id, snapshot_date)
);
CREATE INDEX posting_snapshots_date ON posting_snapshots (snapshot_date);

CREATE TABLE posting_text (
    posting_id         bigint PRIMARY KEY REFERENCES postings (id) ON DELETE CASCADE,
    description_clean  text NOT NULL,
    word_count         int NOT NULL,
    embedding          vector(384),   -- filled in Phase 4
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX posting_text_embedding_hnsw ON posting_text USING hnsw (embedding vector_cosine_ops);
