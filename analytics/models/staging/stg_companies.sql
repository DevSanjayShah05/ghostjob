select
    id as company_id,
    name as company_name,
    ats,
    board_token,
    industry,
    size_bucket,
    -- A rough headcount for each size bucket, used to compare open roles against company size.
    case size_bucket
        when '1-200' then 100
        when '201-1000' then 600
        when '1001-5000' then 3000
        when '5001+' then 10000
    end as size_midpoint,
    hq_state,
    is_tracked
from {{ source('ghostjob', 'companies') }}
