{{ config(alias='loanbook__loan') }}

select
    loan_id,
    borrower_id,
    product_type,
    origination_month,
    principal_amount,
    cast(term_months as integer) as term_months,
    interest_rate,
    monthly_payment as monthly_payment_amount,
    score_band
from {{ source('loanbook', 'loans') }}
