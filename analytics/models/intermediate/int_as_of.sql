-- The date every "as of today" number is computed for: the latest date with a successful run.
-- Using this instead of current_date makes the marts reproducible from the same data.
select coalesce(max(run_date), current_date) as as_of_date
from {{ ref('stg_pipeline_runs') }}
where status in ('success', 'partial')
