-- Open roles per company per day, plus the 30-day change used by the Ghost Score.
with d as (
    select * from {{ ref('int_company_daily') }}
),
with_baseline as (
    select
        d.*,
        -- The earliest tracked day in the 30 days before this one (or this day itself).
        first_value(open_roles) over w as open_roles_window_start,
        first_value(snapshot_date) over w as window_start_date
    from d
    window w as (
        partition by company_id
        order by snapshot_date
        range between interval '30 days' preceding and current row
    )
)
select
    company_id,
    snapshot_date,
    open_roles,
    new_roles,
    closed_roles,
    window_start_date,
    snapshot_date - window_start_date as window_days,
    open_roles - open_roles_window_start as open_roles_change_30d,
    -- Only meaningful once there is at least a week of history; NULL before that.
    case
        when snapshot_date - window_start_date >= 7 and open_roles_window_start > 0
            then round((open_roles - open_roles_window_start)::numeric / open_roles_window_start, 4)
    end as hiring_trend_30d
from with_baseline
