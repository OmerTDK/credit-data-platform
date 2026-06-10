select
    loan_id,
    product_type,
    principal_amount,
    term_months,
    monthly_payment_amount,
    credit_limit_amount
from {{ ref('stg_loanbook__loan') }}
where
    (
        product_type = 'credit_card'
        and (
            credit_limit_amount is null
            or principal_amount is not null
            or term_months is not null
            or monthly_payment_amount is not null
        )
    )
    or (
        product_type <> 'credit_card'
        and (
            credit_limit_amount is not null
            or principal_amount is null
            or term_months is null
            or monthly_payment_amount is null
        )
    )
