with perf as (
    select
        loan_id,
        product_type,
        months_on_book,
        report_month,
        beginning_balance_amount,
        draw_amount,
        scheduled_payment_amount,
        actual_payment_amount,
        principal_paid_amount,
        interest_paid_amount,
        interest_charged_amount,
        ending_balance_amount,
        principal_writeoff_amount,
        recovery_amount,
        utilization_rate,
        delinquency_bucket,
        loan_status,
        is_prepayment
    from {{ ref('stg_loanbook__monthly_performance') }}
)

select
    loan_id,
    product_type,
    months_on_book,
    report_month,
    beginning_balance_amount,
    draw_amount,
    scheduled_payment_amount,
    actual_payment_amount,
    principal_paid_amount,
    interest_paid_amount,
    interest_charged_amount,
    ending_balance_amount,
    principal_writeoff_amount,
    recovery_amount,
    utilization_rate,
    delinquency_bucket,
    loan_status,
    is_prepayment
from perf
