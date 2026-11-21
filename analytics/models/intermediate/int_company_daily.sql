-- One row per company per day on which its board was fetched successfully.
-- Days where the fetch failed are left out on purpose: a gap is "unknown", not "zero open roles".
with ok_days as (
    select distinct company_id, run_date
    from {{ ref('stg_company_fetches') }}
    where fetch_status = 'ok'
),
snap as (
    select p.company_id, s.snapshot_date, s.is_present
    from {{ ref('stg_posting_snapshots') }} as s
    join {{ ref('stg_postings') }} as p using (posting_id)
),
counts as (
    select
        company_id,
        snapshot_date,
        count(*) filter (where is_present) as open_roles,
        count(*) filter (where not is_present) as closed_roles
    from snap
    group by company_id, snapshot_date
),
new_roles as (
    select company_id, first_seen_date as snapshot_date, count(*) as new_roles
    from {{ ref('stg_postings') }}
    group by company_id, first_seen_date
)
select
    d.company_id,
    d.run_date as snapshot_date,
    coalesce(c.open_roles, 0) as open_roles,
    coalesce(n.new_roles, 0) as new_roles,
    coalesce(c.closed_roles, 0) as closed_roles
from ok_days as d
left join counts as c on c.company_id = d.company_id and c.snapshot_date = d.run_date
left join new_roles as n on n.company_id = d.company_id and n.snapshot_date = d.run_date
