select
    borrower_id,
    count(*) as current_row_count
from {{ ref('dim_borrower') }}
where _is_current
group by borrower_id
having count(*) != 1
