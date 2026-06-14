select
    mart_risk_roll_rate_matrix.roll_rate_key,
    mart_risk_roll_rate_matrix.product_type,
    mart_risk_roll_rate_matrix.observation_period
from {{ ref('mart_risk_roll_rate_matrix') }} as mart_risk_roll_rate_matrix
where mart_risk_roll_rate_matrix.from_bucket is null
