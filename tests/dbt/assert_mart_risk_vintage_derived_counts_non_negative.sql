select
    mart_risk_vintage_curve.vintage_curve_key,
    mart_risk_vintage_curve.origination_cohort_quarter,
    mart_risk_vintage_curve.product_type,
    mart_risk_vintage_curve.score_band,
    mart_risk_vintage_curve.months_on_book,
    mart_risk_vintage_curve.surviving_non_defaulted_count,
    mart_risk_vintage_curve.loans_at_risk_count
from {{ ref('mart_risk_vintage_curve') }} as mart_risk_vintage_curve
where
    mart_risk_vintage_curve.surviving_non_defaulted_count < 0
    or mart_risk_vintage_curve.loans_at_risk_count < 0
