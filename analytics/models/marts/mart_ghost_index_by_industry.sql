-- Ghost Index by industry, as of the latest run.
-- Until the Ghost Score model exists (Phase 6), this uses transparent rule-based signals:
--   stale_share      = open >= stale_days (60) days
--   rule_flag_share  = the spec's weak "likely ghost" rule with the signals available today:
--                      stale AND (date_refresh_count >= 3 OR times_reopened >= 2)
-- Phase 6 adds the model-based ghost share next to these.
with f as (
    select * from {{ ref('mart_ghost_features') }}
)
select
    industry,
    max(as_of_date) as as_of_date,
    count(distinct company_id) as companies,
    count(*) as active_postings,
    percentile_cont(0.5) within group (order by days_open) as median_days_open,
    round(avg((days_open >= {{ var('stale_days') }})::int), 4) as stale_share,
    round(avg((
        days_open >= {{ var('stale_days') }}
        and (date_refresh_count >= 3 or times_reopened >= 2)
    )::int), 4) as rule_flag_share,
    round(avg((not has_salary)::int), 4) as no_salary_share,
    round(avg((remote_type = 'remote')::int), 4) as remote_share
from f
group by industry
