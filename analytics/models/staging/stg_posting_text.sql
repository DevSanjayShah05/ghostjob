select
    posting_id,
    word_count,
    embedding is not null as has_embedding,
    updated_at
from {{ source('ghostjob', 'posting_text') }}
