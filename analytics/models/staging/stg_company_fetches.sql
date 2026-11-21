select
    f.run_id,
    r.run_date,
    f.company_id,
    f.status as fetch_status,
    f.jobs_found,
    f.duration_ms,
    f.error
from {{ source('ghostjob', 'company_fetches') }} as f
join {{ source('ghostjob', 'pipeline_runs') }} as r on r.id = f.run_id
