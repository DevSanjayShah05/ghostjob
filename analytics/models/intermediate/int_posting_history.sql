-- One row per posting: what its daily snapshots say about it.
with s as (
    select * from {{ ref('stg_posting_snapshots') }}
)
select
    posting_id,
    min(snapshot_date) as first_snapshot_date,
    max(snapshot_date) filter (where is_present) as last_present_date,
    count(*) filter (where is_present) as days_present,
    count(*) filter (where not is_present) as days_marked_closed,
    -- "Fake freshness": the ATS updated date moved but the text did not change.
    count(*) filter (where is_date_refresh) as date_refresh_count,
    -- Real edits after the first day (the first snapshot always carries the hash).
    greatest(count(*) filter (where content_marked) - 1, 0) as content_change_count
from s
group by posting_id
