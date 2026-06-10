select
    loan_id,
    months_on_book,
    product_type,
    utilization_rate
from {{ ref('stg_loanbook__monthly_performance') }}
where
    (product_type = 'credit_card' and utilization_rate is null)
    or (product_type <> 'credit_card' and utilization_rate is not null)
