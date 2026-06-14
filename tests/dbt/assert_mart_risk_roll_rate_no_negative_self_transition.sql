select
    mart_risk_roll_rate_matrix.product_type,
    mart_risk_roll_rate_matrix.score_band,
    mart_risk_roll_rate_matrix.observation_period,
    mart_risk_roll_rate_matrix.from_bucket,
    mart_risk_roll_rate_matrix.to_bucket,
    mart_risk_roll_rate_matrix.transition_loan_count
from {{ ref('mart_risk_roll_rate_matrix') }} as mart_risk_roll_rate_matrix
where
    mart_risk_roll_rate_matrix.from_bucket = mart_risk_roll_rate_matrix.to_bucket
    and mart_risk_roll_rate_matrix.transition_loan_count < 0
