with ordered_mob as (
    select
        mart_risk_vintage_curve.origination_cohort_quarter,
        mart_risk_vintage_curve.product_type,
        mart_risk_vintage_curve.score_band,
        mart_risk_vintage_curve.months_on_book,
        mart_risk_vintage_curve.cumulative_prepayment_count,
        lag(mart_risk_vintage_curve.cumulative_prepayment_count) over (
            partition by
                mart_risk_vintage_curve.origination_cohort_quarter,
                mart_risk_vintage_curve.product_type,
                mart_risk_vintage_curve.score_band
            order by mart_risk_vintage_curve.months_on_book
        ) as prev_cumulative_prepayment_count
    from {{ ref('mart_risk_vintage_curve') }} as mart_risk_vintage_curve
)

select
    ordered_mob.origination_cohort_quarter,
    ordered_mob.product_type,
    ordered_mob.score_band,
    ordered_mob.months_on_book,
    ordered_mob.prev_cumulative_prepayment_count,
    ordered_mob.cumulative_prepayment_count
from ordered_mob
where
    ordered_mob.prev_cumulative_prepayment_count is not null
    and ordered_mob.cumulative_prepayment_count < ordered_mob.prev_cumulative_prepayment_count
