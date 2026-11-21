-- Phase 4: repost links, per-posting similarity stats, and WARN layoff notices.

-- "Same job, new ID." posting_id is the newer posting, previous_posting_id the copy it repeats.
-- link_type:
--   closed_then_reposted   the old posting closed, and a near-identical one appeared afterwards (the spec's rule)
--   republished_while_open the old posting is still open, and a near-identical one at the same location was
--                          published 30+ days later
CREATE TABLE repost_links (
    posting_id           bigint NOT NULL REFERENCES postings (id) ON DELETE CASCADE,
    previous_posting_id  bigint NOT NULL REFERENCES postings (id) ON DELETE CASCADE,
    link_type            text NOT NULL
                         CHECK (link_type IN ('closed_then_reposted', 'republished_while_open')),
    similarity           real NOT NULL CHECK (similarity BETWEEN -1 AND 1),
    gap_days             int NOT NULL CHECK (gap_days >= 0),
    detected_on          date NOT NULL,
    PRIMARY KEY (posting_id, previous_posting_id),
    CHECK (posting_id <> previous_posting_id)
);
CREATE INDEX repost_links_previous ON repost_links (previous_posting_id);

-- Recomputed every day for active postings (see ghostjob_pipelines/reposts.py).
CREATE TABLE posting_similarity (
    posting_id              bigint PRIMARY KEY REFERENCES postings (id) ON DELETE CASCADE,
    near_dup_open           int NOT NULL,    -- other open postings at the company with cosine >= 0.92,
                                             -- excluding copies published within a day (multi-city batches)
    boilerplate_similarity  real,            -- cosine to the company's average posting (NULL if < 5 postings)
    computed_on             date NOT NULL
);

-- WARN Act layoff notices, matched to tracked companies by name (see ghostjob_pipelines/warn.py).
CREATE TABLE layoff_events (
    id                  bigserial PRIMARY KEY,
    state               char(2) NOT NULL,
    employer_raw        text NOT NULL,
    company_id          int REFERENCES companies (id) ON DELETE SET NULL,   -- NULL = no tracked company matched
    match_score         real,
    notice_date         date NOT NULL,
    effective_date      date,
    employees_affected  int,
    location            text,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (state, employer_raw, notice_date, location)
);
CREATE INDEX layoff_events_company_date ON layoff_events (company_id, notice_date);
