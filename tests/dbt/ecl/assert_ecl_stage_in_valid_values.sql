select
    loan_id,
    scenario_name,
    ifrs9_stage
from {{ ref('mart_finance_ecl_allowance') }}
where ifrs9_stage not in (1, 2, 3)
