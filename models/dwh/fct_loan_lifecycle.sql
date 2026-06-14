{{ config(materialized='table') }}

with loans as (
    select
        loan_id,
        borrower_id,
        product_type,
        origination_month,
        principal_amount,
        term_months
    from {{ ref('int_loan') }}
),

perf as (
    select
        loan_id,
        months_on_book,
        report_month,
        delinquency_bucket,
        loan_status,
        is_prepayment,
        principal_writeoff_amount,
        recovery_amount,
        ending_balance_amount
    from {{ ref('int_monthly_performance') }}
),

first_payment as (
    select
        loan_id,
        min(report_month) as first_payment_month
    from perf
    group by loan_id
),

first_dpd30 as (
    select
        loan_id,
        min(report_month) as first_dpd30_month
    from perf
    where delinquency_bucket in ('dpd_30', 'dpd_60', 'dpd_90_plus', 'default')
    group by loan_id
),

first_dpd60 as (
    select
        loan_id,
        min(report_month) as first_dpd60_month
    from perf
    where delinquency_bucket in ('dpd_60', 'dpd_90_plus', 'default')
    group by loan_id
),

first_dpd90 as (
    select
        loan_id,
        min(report_month) as first_dpd90_month
    from perf
    where delinquency_bucket in ('dpd_90_plus', 'default')
    group by loan_id
),

default_event as (
    select
        loan_id,
        min(report_month) as default_month
    from perf
    where loan_status = 'defaulted'
    group by loan_id
),

payoff_event as (
    select
        loan_id,
        min(report_month) as payoff_month
    from perf
    where loan_status = 'paid_off'
    group by loan_id
),

prepayment_event as (
    select
        loan_id,
        min(report_month) as prepayment_month
    from perf
    where is_prepayment
    group by loan_id
),

recovery_event as (
    select
        loan_id,
        min(report_month) as recovery_complete_month
    from perf
    where loan_status = 'recovery_complete'
    group by loan_id
),

latest_mob as (
    select
        loan_id,
        max(months_on_book) as latest_mob
    from perf
    group by loan_id
),

last_perf as (
    select
        perf.loan_id,
        perf.report_month as last_report_month,
        perf.months_on_book as total_months_on_book,
        perf.loan_status as final_status,
        perf.ending_balance_amount as final_balance_amount
    from perf
    inner join latest_mob
        on
            perf.loan_id = latest_mob.loan_id
            and perf.months_on_book = latest_mob.latest_mob
)

select
    {{ generate_surrogate_key(['loans.loan_id']) }} as loan_lifecycle_key,
    {{ generate_surrogate_key(['loans.loan_id']) }} as loan_key,
    {{ generate_surrogate_key(['loans.borrower_id']) }} as borrower_key,
    {{ generate_surrogate_key(['loans.product_type']) }} as product_key,
    cast(strftime(loans.origination_month, '%Y%m%d') as integer) as origination_date_key,
    cast(strftime(fp.first_payment_month, '%Y%m%d') as integer) as first_payment_date_key,
    cast(strftime(fd30.first_dpd30_month, '%Y%m%d') as integer) as first_dpd30_date_key,
    cast(strftime(fd60.first_dpd60_month, '%Y%m%d') as integer) as first_dpd60_date_key,
    cast(strftime(fd90.first_dpd90_month, '%Y%m%d') as integer) as first_dpd90_date_key,
    cast(strftime(de.default_month, '%Y%m%d') as integer) as default_date_key,
    cast(strftime(pe.payoff_month, '%Y%m%d') as integer) as payoff_date_key,
    cast(strftime(prep.prepayment_month, '%Y%m%d') as integer) as prepayment_date_key,
    cast(strftime(re.recovery_complete_month, '%Y%m%d') as integer) as recovery_complete_date_key,
    loans.loan_id,
    loans.borrower_id,
    loans.product_type,
    loans.origination_month,
    loans.principal_amount,
    loans.term_months,
    fp.first_payment_month,
    fd30.first_dpd30_month,
    fd60.first_dpd60_month,
    fd90.first_dpd90_month,
    de.default_month,
    pe.payoff_month,
    prep.prepayment_month,
    re.recovery_complete_month,
    lp.last_report_month,
    lp.total_months_on_book,
    lp.final_status,
    lp.final_balance_amount,
    lp.final_status in ('paid_off', 'defaulted', 'recovery_complete') as is_terminal,
    de.default_month is not null as has_defaulted,
    pe.payoff_month is not null as has_paid_off,
    prep.prepayment_month is not null as has_prepaid,
    fd30.first_dpd30_month is not null as has_been_delinquent,
    current_timestamp as _loaded_at
from loans
left join first_payment as fp on loans.loan_id = fp.loan_id
left join first_dpd30 as fd30 on loans.loan_id = fd30.loan_id
left join first_dpd60 as fd60 on loans.loan_id = fd60.loan_id
left join first_dpd90 as fd90 on loans.loan_id = fd90.loan_id
left join default_event as de on loans.loan_id = de.loan_id
left join payoff_event as pe on loans.loan_id = pe.loan_id
left join prepayment_event as prep on loans.loan_id = prep.loan_id
left join recovery_event as re on loans.loan_id = re.loan_id
left join last_perf as lp on loans.loan_id = lp.loan_id
