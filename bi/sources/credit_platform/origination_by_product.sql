-- Origination volume and loan count by product and credit tier.
select
    product_type,
    score_band as credit_tier,
    count(*) as loan_count,
    sum(principal_amount) as origination_volume
from dwh.fct_loan_origination
group by product_type, score_band
order by product_type, score_band
