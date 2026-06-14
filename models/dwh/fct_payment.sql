{{ config(materialized='table') }}

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
    from {{ ref('int_monthly_performance') }}
),

loans as (
    select
        loan_id,
        borrower_id
    from {{ ref('int_loan') }}
)

select
    {{ generate_surrogate_key(['perf.loan_id', 'perf.months_on_book']) }}          as payment_key,
    {{ generate_surrogate_key(['perf.loan_id']) }}                                  as loan_key,
    {{ generate_surrogate_key(['loans.borrower_id']) }}                             as borrower_key,
    {{ generate_surrogate_key(['perf.product_type']) }}                             as product_key,
    cast(strftime(perf.report_month, '%Y%m%d') as integer) as payment_date_key,
    perf.loan_id,
    perf.product_type,
    perf.months_on_book,
    perf.report_month,
    perf.beginning_balance_amount,
    perf.draw_amount,
    perf.scheduled_payment_amount,
    perf.actual_payment_amount,
    perf.principal_paid_amount,
    perf.interest_paid_amount,
    perf.interest_charged_amount,
    perf.ending_balance_amount,
    perf.principal_writeoff_amount,
    perf.recovery_amount,
    perf.utilization_rate,
    perf.delinquency_bucket,
    perf.loan_status,
    perf.is_prepayment,
    perf.actual_payment_amount >= perf.scheduled_payment_amount as is_paid_in_full,
    perf.actual_payment_amount = 0 as is_missed_payment,
    current_timestamp as _loaded_at
from perf
inner join loans on perf.loan_id = loans.loan_id
