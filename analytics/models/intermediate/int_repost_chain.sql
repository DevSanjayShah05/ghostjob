-- For every posting that has at least one earlier copy: how many earlier copies it has (following the chain
-- A <- B <- C back), and how many of those were published in the 180 days before it (repost_count_180d).
with recursive links as (
    select posting_id, previous_posting_id from {{ ref('stg_repost_links') }}
),
starts as (
    select posting_id, coalesce(source_created_at, first_seen_at) as started_at
    from {{ ref('stg_postings') }}
),
chain as (
    select posting_id as root_id, previous_posting_id as ancestor_id, 1 as depth
    from links
    union all
    select c.root_id, l.previous_posting_id, c.depth + 1
    from chain as c
    join links as l on l.posting_id = c.ancestor_id
    where c.depth < 50  -- guard against a cycle in bad data
)
select
    c.root_id as posting_id,
    count(*) as earlier_copies,
    count(*) filter (where sa.started_at >= sr.started_at - interval '180 days') as repost_count_180d,
    min(sa.started_at) as first_copy_started_at
from chain as c
join starts as sr on sr.posting_id = c.root_id
join starts as sa on sa.posting_id = c.ancestor_id
group by c.root_id
