{{ config(
    materialized='table',
    contract={'enforced': true}
) }}

with observations as (
    select
        product_type,
        score_band,
        observation_period,
        period_length_months,
        from_bucket,
        to_bucket,
        transition_count,
        transition_balance_sum,
        at_risk_count,
        beginning_balance_sum,
        is_low_count_cell
    from {{ ref('int_risk_roll_rate_observations') }}
)

select
    {{ generate_surrogate_key([
        'observations.product_type',
        'observations.score_band',
        'cast(observations.observation_period as varchar)',
        'observations.from_bucket',
        'observations.to_bucket'
    ]) }}                                                                as roll_rate_key,
    observations.product_type,
    observations.score_band,
    observations.observation_period,
    observations.period_length_months,
    observations.from_bucket,
    observations.to_bucket,
    cast(observations.transition_count as integer) as transition_loan_count,
    cast(observations.at_risk_count as integer) as at_risk_loan_count,
    cast(observations.transition_balance_sum as decimal(18, 2)) as transition_balance,
    cast(observations.beginning_balance_sum as decimal(18, 2)) as at_risk_balance,
    cast(
        cast(observations.transition_count as double) / nullif(observations.at_risk_count, 0)
        as decimal(10, 6)
    ) as transition_rate,
    cast(
        cast(observations.transition_balance_sum as double)
        / nullif(observations.beginning_balance_sum, 0)
        as decimal(10, 6)
    ) as transition_balance_rate,
    observations.is_low_count_cell,
    current_timestamp as _loaded_at
from observations
