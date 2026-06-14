select
    loan_id,
    current_delinquency_bucket,
    ifrs9_stage
from {{ ref('int_ecl_staging') }}
where
    current_delinquency_bucket = 'dpd_60'
    and ifrs9_stage = 1
