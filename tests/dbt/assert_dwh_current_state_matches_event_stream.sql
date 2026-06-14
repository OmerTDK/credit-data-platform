with inner_ranked as (
    select
        perf.loan_id,
        perf.loan_status,
        perf.delinquency_bucket,
        row_number() over (
            partition by perf.loan_id
            order by perf.months_on_book desc
        ) as rn
    from {{ ref('int_monthly_performance') }} as perf
),

direct_current as (
    select
        inner_ranked.loan_id,
        inner_ranked.loan_status as direct_loan_status,
        inner_ranked.delinquency_bucket as direct_delinquency_bucket
    from inner_ranked
    where inner_ranked.rn = 1
),

event_derived as (
    select
        dim_loan_current_state.loan_id,
        dim_loan_current_state.current_loan_status,
        dim_loan_current_state.current_delinquency_bucket
    from {{ ref('dim_loan_current_state') }}
)

select
    event_derived.loan_id,
    event_derived.current_loan_status,
    direct_current.direct_loan_status,
    event_derived.current_delinquency_bucket,
    direct_current.direct_delinquency_bucket
from event_derived
inner join direct_current
    on event_derived.loan_id = direct_current.loan_id
where
    event_derived.current_loan_status != direct_current.direct_loan_status
    or event_derived.current_delinquency_bucket != direct_current.direct_delinquency_bucket
