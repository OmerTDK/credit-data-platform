select
    mart_risk_prepayment_speed.prepayment_speed_key,
    mart_risk_prepayment_speed.origination_cohort_quarter,
    mart_risk_prepayment_speed.product_type,
    mart_risk_prepayment_speed.months_on_book,
    mart_risk_prepayment_speed.smm_rate,
    mart_risk_prepayment_speed.cpr_rate
from {{ ref('mart_risk_prepayment_speed') }} as mart_risk_prepayment_speed
where
    mart_risk_prepayment_speed.smm_rate is not null
    and (
        mart_risk_prepayment_speed.smm_rate < 0
        or mart_risk_prepayment_speed.smm_rate > 1
    )
