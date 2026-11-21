-- One row per posting per tracked day: the full history in analysis-friendly form.
-- Materialized as a view: it grows by ~27k rows a day, and storing it would use the free
-- database's space for no gain (it is a cheap join over posting_snapshots).
{{ config(materialized='view') }}

select
    s.posting_id,
    p.company_id,
    s.snapshot_date,
    s.run_id,
    s.is_present,
    s.is_date_refresh,
    s.content_marked and s.snapshot_date > h.first_snapshot_date as is_content_change,
    s.snapshot_date - a.opened_date as days_open_on_date
from {{ ref('stg_posting_snapshots') }} as s
join {{ ref('stg_postings') }} as p using (posting_id)
join {{ ref('int_posting_age') }} as a using (posting_id)
join {{ ref('int_posting_history') }} as h using (posting_id)
