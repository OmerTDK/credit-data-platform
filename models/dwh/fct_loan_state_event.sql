{{ config(materialized='table') }}

with perf as (
    select
        loan_id,
        product_type,
        months_on_book,
        report_month,
        delinquency_bucket,
        loan_status
    from {{ ref('int_monthly_performance') }}
),

loans as (
    select
        loan_id,
        borrower_id
    from {{ ref('int_loan') }}
),

ordered as (
    select
        perf.loan_id,
        perf.product_type,
        perf.months_on_book,
        perf.report_month,
        perf.delinquency_bucket,
        perf.loan_status,
        lag(perf.delinquency_bucket) over (
            partition by perf.loan_id
            order by perf.months_on_book
        ) as prev_delinquency_bucket,
        lag(perf.loan_status) over (
            partition by perf.loan_id
            order by perf.months_on_book
        ) as prev_loan_status
    from perf
),

state_changes as (
    select
        loan_id,
        product_type,
        months_on_book,
        report_month,
        delinquency_bucket as to_delinquency_bucket,
        prev_delinquency_bucket as from_delinquency_bucket,
        loan_status as to_loan_status,
        prev_loan_status as from_loan_status,
        case
            when prev_delinquency_bucket is null then 'origination'
            when prev_delinquency_bucket != delinquency_bucket then 'delinquency_transition'
            when
                loan_status != coalesce(prev_loan_status, loan_status)
                and loan_status in ('paid_off', 'defaulted', 'recovery_complete')
                then 'lifecycle_transition'
        end as event_type
    from ordered
    where
        prev_delinquency_bucket is null
        or prev_delinquency_bucket != delinquency_bucket
        or (
            loan_status != coalesce(prev_loan_status, loan_status)
            and loan_status in ('paid_off', 'defaulted', 'recovery_complete')
        )
)

select
    {{ generate_surrogate_key(['sc.loan_id', 'sc.months_on_book', 'sc.event_type']) }} as state_event_key,
    {{ generate_surrogate_key(['sc.loan_id']) }}                                        as loan_key,
    {{ generate_surrogate_key(['loans.borrower_id']) }}                                 as borrower_key,
    {{ generate_surrogate_key(['sc.product_type']) }}                                   as product_key,
    cast(strftime(sc.report_month, '%Y%m%d') as integer) as event_date_key,
    sc.loan_id,
    sc.product_type,
    sc.months_on_book,
    sc.report_month,
    sc.event_type,
    sc.from_delinquency_bucket,
    sc.to_delinquency_bucket,
    sc.from_loan_status,
    sc.to_loan_status,
    current_timestamp as _loaded_at
from state_changes as sc
inner join loans on sc.loan_id = loans.loan_id
