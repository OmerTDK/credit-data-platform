select
    loan_id,
    months_on_book,
    count(*) as duplicate_row_count
from {{ ref('stg_loanbook__monthly_performance') }}
group by loan_id, months_on_book
having count(*) > 1
