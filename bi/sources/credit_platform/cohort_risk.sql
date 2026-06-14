-- Risk-cohort drill-down: lifetime default and prepayment rates by credit tier
-- and product. Credit tier (score_band) lives on the origination fact; the
-- lifecycle fact carries the terminal-outcome flags. One row per
-- (credit_tier, product).
select
    origination.score_band as credit_tier,
    lifecycle.product_type,
    count(*) as loan_count,
    avg(case when lifecycle.has_defaulted then 1.0 else 0.0 end) as default_rate,
    avg(case when lifecycle.has_prepaid then 1.0 else 0.0 end) as prepayment_rate
from dwh.fct_loan_lifecycle as lifecycle
inner join dwh.fct_loan_origination as origination
    on lifecycle.loan_id = origination.loan_id
group by origination.score_band, lifecycle.product_type
order by origination.score_band, lifecycle.product_type
