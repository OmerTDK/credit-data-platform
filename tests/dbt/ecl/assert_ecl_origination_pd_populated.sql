select
    loan_id,
    current_loan_status,
    product_type,
    score_band,
    origination_pd_rate
from {{ ref('int_ecl_staging') }}
where
    not is_terminal
    and origination_pd_rate is null
