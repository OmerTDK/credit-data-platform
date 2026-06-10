{{ config(alias='loanbook__monthly_performance') }}

select
    loan_id,
    product_type,
    cast(period as integer) as months_on_book,
    report_month,
    beginning_balance as beginning_balance_amount,
    draw_amount,
    scheduled_payment as scheduled_payment_amount,
    actual_payment as actual_payment_amount,
    principal_paid as principal_paid_amount,
    interest_paid as interest_paid_amount,
    interest_charged as interest_charged_amount,
    ending_balance as ending_balance_amount,
    principal_writeoff as principal_writeoff_amount,
    recovery_amount,
    utilization_rate,
    delinquency_bucket,
    loan_status,
    is_prepayment
from {{ source('loanbook', 'monthly_performance') }}
