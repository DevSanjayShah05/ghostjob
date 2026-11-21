-- How long each posting has been open.
-- GhostJob started tracking on 2026-11-21, so for older postings we backfill with the ATS's own
-- publish date (source_created_at) when it is earlier than our first sighting.
with p as (
    select * from {{ ref('stg_postings') }}
),
a as (
    select as_of_date from {{ ref('int_as_of') }}
)
select
    p.posting_id,
    least(p.first_seen_date, coalesce(p.source_created_date, p.first_seen_date)) as opened_date,
    coalesce(p.source_created_date, p.first_seen_date) < p.first_seen_date as age_is_backfilled,
    coalesce(p.closed_date, a.as_of_date) as age_end_date,
    coalesce(p.closed_date, a.as_of_date)
        - least(p.first_seen_date, coalesce(p.source_created_date, p.first_seen_date)) as days_open,
    coalesce(p.closed_date, a.as_of_date) - p.first_seen_date as days_open_observed
from p
cross join a
