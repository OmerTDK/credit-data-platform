select
    mart_risk_vintage_curve.vintage_curve_key,
    mart_risk_vintage_curve.origination_cohort_quarter,
    mart_risk_vintage_curve.product_type,
    mart_risk_vintage_curve.score_band,
    mart_risk_vintage_curve.months_on_book,
    mart_risk_vintage_curve.cumulative_prepayment_rate
from {{ ref('mart_risk_vintage_curve') }} as mart_risk_vintage_curve
where
    mart_risk_vintage_curve.cumulative_prepayment_rate is not null
    and (
        mart_risk_vintage_curve.cumulative_prepayment_rate < 0
        or mart_risk_vintage_curve.cumulative_prepayment_rate > 1
    )
