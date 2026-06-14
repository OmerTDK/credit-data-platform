select
    borrower_id,
    version_number,
    _valid_from,
    lag(_valid_from) over (
        partition by borrower_id
        order by version_number
    ) as prev_valid_from
from {{ ref('dim_borrower') }}
qualify
    lag(_valid_from) over (partition by borrower_id order by version_number) >= _valid_from
