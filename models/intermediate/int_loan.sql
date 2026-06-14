with loans as (
    select
        loan_id,
        borrower_id,
        product_type,
        origination_month,
        principal_amount,
        term_months,
        interest_rate,
        monthly_payment_amount,
        credit_limit_amount,
        score_band
    from {{ ref('stg_loanbook__loan') }}
)

select
    loan_id,
    borrower_id,
    product_type,
    origination_month,
    principal_amount,
    term_months,
    interest_rate,
    monthly_payment_amount,
    credit_limit_amount,
    score_band
from loans
