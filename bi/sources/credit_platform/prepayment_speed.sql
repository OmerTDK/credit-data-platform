-- Prepayment speed (annualized CPR) by cohort, product, and months on book.
select
    cast(origination_cohort_quarter as varchar) as cohort_quarter,
    product_type,
    months_on_book,
    cpr_rate,
    smm_rate
from mart_risk.mart_risk_prepayment_speed
where cpr_rate is not null
order by cohort_quarter, product_type, months_on_book
