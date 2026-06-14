{{ config(materialized='table') }}

with events as (
    select
        loan_key,
        loan_id,
        event_date_key,
        report_month,
        months_on_book,
        to_delinquency_bucket,
        to_loan_status,
        event_type
    from {{ ref('fct_loan_state_event') }}
),

latest_event as (
    select
        loan_key,
        loan_id,
        max(months_on_book) as latest_mob
    from events
    group by loan_key, loan_id
),

current_state as (
    select
        events.loan_key,
        events.loan_id,
        events.event_date_key as state_as_of_date_key,
        events.report_month as state_as_of_month,
        events.months_on_book,
        events.to_delinquency_bucket as current_delinquency_bucket,
        events.to_loan_status as current_loan_status
    from events
    inner join latest_event
        on
            events.loan_id = latest_event.loan_id
            and events.months_on_book = latest_event.latest_mob
)

select
    loan_key,
    loan_id,
    state_as_of_date_key,
    state_as_of_month,
    months_on_book,
    current_delinquency_bucket,
    current_loan_status,
    current_loan_status in ('paid_off', 'defaulted', 'recovery_complete') as is_terminal,
    current_timestamp as _loaded_at
from current_state
