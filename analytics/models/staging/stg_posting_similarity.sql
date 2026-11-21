select
    posting_id,
    near_dup_open,
    boilerplate_similarity,
    computed_on
from {{ source('ghostjob', 'posting_similarity') }}
