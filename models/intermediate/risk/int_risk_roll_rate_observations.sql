-- Mart-prep intermediate. Reads DWH facts/dimensions to build risk-specific
-- projection for downstream mart_risk_roll_rate_matrix mart.

{{ config(materialized='view') }}

with constants as (
    select
        10 as minimum_cell_count,
        {{ var('roll_rate_period_months', 1) }} as months_per_period
),

loan_period_starts as (
    select
        fct_payment.loan_id,
        fct_payment.product_type,
        dim_loan.score_band,
        cast(date_trunc(
            'month',
            fct_payment.report_month + interval (constants.months_per_period) month
        ) as date) as observation_period,
        fct_payment.delinquency_bucket as from_bucket,
        fct_payment.beginning_balance_amount,
        fct_payment.months_on_book + constants.months_per_period as next_months_on_book
    from {{ ref('fct_payment') }} as fct_payment
    inner join {{ ref('dim_loan') }} as dim_loan
        on fct_payment.loan_id = dim_loan.loan_id
    cross join constants
    where fct_payment.loan_status = 'active'
),

transition_events as (
    select
        fct_loan_state_event.loan_id,
        fct_loan_state_event.product_type,
        dim_loan.score_band,
        fct_loan_state_event.from_delinquency_bucket as from_bucket,
        fct_loan_state_event.to_delinquency_bucket as to_bucket,
        cast(date_trunc(
            'month',
            fct_loan_state_event.report_month
        ) as date) as observation_period
    from {{ ref('fct_loan_state_event') }} as fct_loan_state_event
    inner join {{ ref('dim_loan') }} as dim_loan
        on fct_loan_state_event.loan_id = dim_loan.loan_id
    where fct_loan_state_event.event_type = 'delinquency_transition'
),

at_risk_denominator as (
    select
        loan_period_starts.product_type,
        loan_period_starts.score_band,
        loan_period_starts.observation_period,
        loan_period_starts.from_bucket,
        count(distinct loan_period_starts.loan_id) as at_risk_count,
        sum(loan_period_starts.beginning_balance_amount) as beginning_balance_sum
    from loan_period_starts
    inner join {{ ref('fct_payment') }} as subsequent_payment
        on
            loan_period_starts.loan_id = subsequent_payment.loan_id
            and loan_period_starts.next_months_on_book = subsequent_payment.months_on_book
    group by
        loan_period_starts.product_type,
        loan_period_starts.score_band,
        loan_period_starts.observation_period,
        loan_period_starts.from_bucket
),

non_self_transitions as (
    select
        transition_events.product_type,
        transition_events.score_band,
        transition_events.observation_period,
        transition_events.from_bucket,
        transition_events.to_bucket,
        count(distinct transition_events.loan_id) as transition_count,
        sum(lps.beginning_balance_amount) as transition_balance_sum
    from transition_events
    inner join loan_period_starts as lps
        on
            transition_events.loan_id = lps.loan_id
            and transition_events.observation_period = lps.observation_period
            and transition_events.from_bucket = lps.from_bucket
    group by
        transition_events.product_type,
        transition_events.score_band,
        transition_events.observation_period,
        transition_events.from_bucket,
        transition_events.to_bucket
),

non_self_aggregated as (
    select
        non_self_transitions.product_type,
        non_self_transitions.score_band,
        non_self_transitions.observation_period,
        non_self_transitions.from_bucket,
        sum(non_self_transitions.transition_count) as total_non_self_transition_count,
        sum(non_self_transitions.transition_balance_sum) as total_non_self_balance
    from non_self_transitions
    group by
        non_self_transitions.product_type,
        non_self_transitions.score_band,
        non_self_transitions.observation_period,
        non_self_transitions.from_bucket
),

self_transitions as (
    select
        at_risk_denominator.product_type,
        at_risk_denominator.score_band,
        at_risk_denominator.observation_period,
        at_risk_denominator.from_bucket,
        at_risk_denominator.from_bucket as to_bucket,
        at_risk_denominator.at_risk_count - coalesce(
            non_self_aggregated.total_non_self_transition_count, 0
        ) as transition_count,
        at_risk_denominator.beginning_balance_sum - coalesce(
            non_self_aggregated.total_non_self_balance, 0
        ) as transition_balance_sum
    from at_risk_denominator
    left join non_self_aggregated
        on
            at_risk_denominator.product_type = non_self_aggregated.product_type
            and at_risk_denominator.score_band = non_self_aggregated.score_band
            and at_risk_denominator.observation_period = non_self_aggregated.observation_period
            and at_risk_denominator.from_bucket = non_self_aggregated.from_bucket
),

all_observations as (
    select
        non_self_transitions.product_type,
        non_self_transitions.score_band,
        non_self_transitions.observation_period,
        non_self_transitions.from_bucket,
        non_self_transitions.to_bucket,
        non_self_transitions.transition_count,
        non_self_transitions.transition_balance_sum,
        at_risk_denominator.at_risk_count,
        at_risk_denominator.beginning_balance_sum
    from non_self_transitions
    inner join at_risk_denominator
        on
            non_self_transitions.product_type = at_risk_denominator.product_type
            and non_self_transitions.score_band = at_risk_denominator.score_band
            and non_self_transitions.observation_period = at_risk_denominator.observation_period
            and non_self_transitions.from_bucket = at_risk_denominator.from_bucket

    union all

    select
        self_transitions.product_type,
        self_transitions.score_band,
        self_transitions.observation_period,
        self_transitions.from_bucket,
        self_transitions.to_bucket,
        self_transitions.transition_count,
        self_transitions.transition_balance_sum,
        at_risk_denominator.at_risk_count,
        at_risk_denominator.beginning_balance_sum
    from self_transitions
    inner join at_risk_denominator
        on
            self_transitions.product_type = at_risk_denominator.product_type
            and self_transitions.score_band = at_risk_denominator.score_band
            and self_transitions.observation_period = at_risk_denominator.observation_period
            and self_transitions.from_bucket = at_risk_denominator.from_bucket
)

select
    all_observations.product_type,
    all_observations.score_band,
    all_observations.observation_period,
    constants.months_per_period as period_length_months,
    all_observations.from_bucket,
    all_observations.to_bucket,
    all_observations.transition_count,
    all_observations.transition_balance_sum,
    all_observations.at_risk_count,
    all_observations.beginning_balance_sum,
    all_observations.at_risk_count < constants.minimum_cell_count as is_low_count_cell
from all_observations
cross join constants
