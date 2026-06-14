-- Vintage loss curve: cumulative default rate by origination cohort and months
-- on book, aggregated across credit tiers within each (cohort, product).
select
    cast(origination_cohort_quarter as varchar) as cohort_quarter,
    product_type,
    months_on_book,
    sum(cumulative_default_count) as cumulative_defaults,
    sum(cohort_loan_count) as cohort_exposure,
    sum(cumulative_default_count)::double
        / nullif(sum(cohort_loan_count), 0) as vintage_loss_curve
from mart_risk.mart_risk_vintage_curve
group by origination_cohort_quarter, product_type, months_on_book
order by cohort_quarter, product_type, months_on_book
