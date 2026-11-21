-- One row per ACTIVE posting: the inputs to the Ghost Score model (Phase 6).
-- Columns that depend on later phases are present but NULL until then, so the model's input
-- contract is fixed now:
--   repost_count_180d, boilerplate_similarity, similar_open_same_company come from Phase 4 (embeddings)
--   vagueness_score, evergreen_flag            -> Phase 5 (LLM layer)
--   company_layoff_90d                         -> WARN layoff data (see docs/DECISIONS.md)
with p as (
    select * from {{ ref('stg_postings') }} where is_active
),
a as (
    select * from {{ ref('int_posting_age') }}
),
h as (
    select * from {{ ref('int_posting_history') }}
),
c as (
    select * from {{ ref('dim_company') }}
),
sim as (
    -- Embedding-based (Phase 4): near-duplicates open at the same company, excluding same-day multi-city copies.
    select * from {{ ref('stg_posting_similarity') }}
),
reposts as (
    select * from {{ ref('int_repost_chain') }}
),
trend as (
    select distinct on (company_id) company_id, hiring_trend_30d
    from {{ ref('mart_company_hiring_trend') }}
    order by company_id, snapshot_date desc
),
txt as (
    select * from {{ ref('stg_posting_text') }}
)
select
    p.posting_id,
    p.company_id,
    (select as_of_date from {{ ref('int_as_of') }}) as as_of_date,
    -- time
    a.days_open,
    a.days_open_observed,
    a.age_is_backfilled,
    -- reposting / freshness
    coalesce(r.repost_count_180d, 0) as repost_count_180d,
    p.times_reopened,
    coalesce(h.date_refresh_count, 0) as date_refresh_count,
    coalesce(h.content_change_count, 0) as content_change_count,
    sim.near_dup_open as similar_open_same_company,  -- NULL until the posting is embedded
    -- company context
    c.open_roles_per_1k_employees as company_open_roles_per_size,
    cast(null as boolean) as company_layoff_90d,
    t.hiring_trend_30d as company_hiring_trend_30d,
    -- pay transparency
    p.has_salary,
    p.salary_range_ratio,
    -- text
    cast(null as numeric) as vagueness_score,
    cast(null as boolean) as evergreen_flag,
    txt.word_count as description_word_count,
    sim.boilerplate_similarity,
    -- controls
    p.seniority,
    p.remote_type,
    c.industry,
    c.size_bucket
from p
join a using (posting_id)
left join h using (posting_id)
join c using (company_id)
left join sim on sim.posting_id = p.posting_id
left join reposts as r on r.posting_id = p.posting_id
left join trend as t on t.company_id = p.company_id
left join txt on txt.posting_id = p.posting_id
