select
    id as run_id,
    run_date,
    started_at,
    finished_at,
    status,
    trigger,
    companies_total,
    companies_ok,
    companies_failed,
    postings_seen,
    postings_new,
    postings_closed,
    postings_reopened,
    postings_changed,
    quality_notes
from {{ source('ghostjob', 'pipeline_runs') }}
