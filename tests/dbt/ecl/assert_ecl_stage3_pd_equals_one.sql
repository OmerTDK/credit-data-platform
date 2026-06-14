select
    loan_id,
    scenario_name,
    ifrs9_stage,
    pd_rate
from {{ ref('mart_finance_ecl_allowance') }}
where
    ifrs9_stage = 3
    and scenario_name != 'probability_weighted'
    and abs(pd_rate - 1.0) > 0.0001
