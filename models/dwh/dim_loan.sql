{{ config(materialized='table') }}

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
    from {{ ref('int_loan') }}
)

select
    {{ generate_surrogate_key(['loan_id']) }}         as loan_key,
    {{ generate_surrogate_key(['borrower_id']) }}     as borrower_key,
    {{ generate_surrogate_key(['product_type']) }}    as product_key,
    cast(strftime(origination_month, '%Y%m%d') as integer) as origination_date_key,
    loan_id,
    borrower_id,
    product_type,
    origination_month,
    principal_amount,
    term_months,
    interest_rate,
    monthly_payment_amount,
    credit_limit_amount,
    score_band,
    product_type in ('personal_loan', 'auto_loan', 'mortgage') as is_amortizing,
    product_type = 'credit_card' as is_revolving,
    current_timestamp as _loaded_at
from loans
