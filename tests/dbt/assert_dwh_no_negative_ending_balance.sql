select
    loan_id,
    months_on_book,
    ending_balance_amount
from {{ ref('fct_payment') }}
where ending_balance_amount < 0
