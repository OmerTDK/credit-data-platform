with constants as (
    select 0.001 as tolerance
),

probability_sums as (
    select
        mart_risk_roll_rate_matrix.product_type,
        mart_risk_roll_rate_matrix.score_band,
        mart_risk_roll_rate_matrix.observation_period,
        mart_risk_roll_rate_matrix.from_bucket,
        sum(mart_risk_roll_rate_matrix.transition_loan_count) as total_transition_count,
        max(mart_risk_roll_rate_matrix.at_risk_loan_count) as at_risk_loan_count
    from {{ ref('mart_risk_roll_rate_matrix') }} as mart_risk_roll_rate_matrix
    group by
        mart_risk_roll_rate_matrix.product_type,
        mart_risk_roll_rate_matrix.score_band,
        mart_risk_roll_rate_matrix.observation_period,
        mart_risk_roll_rate_matrix.from_bucket
)

select
    probability_sums.product_type,
    probability_sums.score_band,
    probability_sums.observation_period,
    probability_sums.from_bucket,
    probability_sums.total_transition_count,
    probability_sums.at_risk_loan_count,
    abs(probability_sums.total_transition_count - probability_sums.at_risk_loan_count) as discrepancy
from probability_sums
cross join constants
where
    abs(probability_sums.total_transition_count - probability_sums.at_risk_loan_count)
    > constants.tolerance
    and probability_sums.at_risk_loan_count > 0
