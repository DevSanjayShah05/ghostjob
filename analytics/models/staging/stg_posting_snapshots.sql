select
    posting_id,
    snapshot_date,
    run_id,
    is_present,
    content_hash is not null as content_marked,
    -- The ATS bumped its "updated" date but the text a job seeker reads didn't change.
    (source_updated_at is not null and content_hash is null) as is_date_refresh
from {{ source('ghostjob', 'posting_snapshots') }}
