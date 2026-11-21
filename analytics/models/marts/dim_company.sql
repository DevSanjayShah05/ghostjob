-- One row per company, with its current hiring footprint.
with c as (
    select * from {{ ref('stg_companies') }}
),
p as (
    select p.*, a.days_open
    from {{ ref('stg_postings') }} as p
    join {{ ref('int_posting_age') }} as a using (posting_id)
),
agg as (
    select
        company_id,
        count(*) as postings_tracked_total,
        count(*) filter (where is_active) as open_roles,
        percentile_cont(0.5) within group (order by days_open) filter (where is_active)
            as median_days_open,
        avg(has_salary::int) filter (where is_active) as share_with_salary,
        min(first_seen_date) as first_seen_date
    from p
    group by company_id
),
last_fetch as (
    select distinct on (company_id) company_id, fetch_status as last_fetch_status, run_date
    from {{ ref('stg_company_fetches') }}
    order by company_id, run_id desc
)
select
    c.company_id,
    c.company_name,
    c.ats,
    c.board_token,
    c.industry,
    c.size_bucket,
    c.size_midpoint,
    c.hq_state,
    c.is_tracked,
    coalesce(agg.postings_tracked_total, 0) as postings_tracked_total,
    coalesce(agg.open_roles, 0) as open_roles,
    -- Open roles per 1,000 employees (rough: uses the size bucket midpoint).
    round(1000.0 * coalesce(agg.open_roles, 0) / c.size_midpoint, 2) as open_roles_per_1k_employees,
    agg.median_days_open,
    round(agg.share_with_salary::numeric, 3) as share_with_salary,
    agg.first_seen_date,
    lf.last_fetch_status,
    lf.run_date as last_fetch_date
from c
left join agg using (company_id)
left join last_fetch as lf using (company_id)
