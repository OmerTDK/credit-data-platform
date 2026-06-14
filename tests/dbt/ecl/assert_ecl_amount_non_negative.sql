select
    loan_id,
    scenario_name,
    ecl_amount
from {{ ref('mart_finance_ecl_allowance') }}
where ecl_amount < 0
