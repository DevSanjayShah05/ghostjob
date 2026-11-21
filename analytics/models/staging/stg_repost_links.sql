select
    posting_id,
    previous_posting_id,
    link_type,
    similarity,
    gap_days,
    detected_on
from {{ source('ghostjob', 'repost_links') }}
