select
    loan_id,
    current_lifetime_pd,
    origination_pd_rate,
    ifrs9_stage
from {{ ref('int_ecl_staging') }}
where
    origination_pd_rate > 0.0
    and current_lifetime_pd / origination_pd_rate > {{ var('ecl_sicr_lifetime_pd_multiple') }}
    and ifrs9_stage = 1
