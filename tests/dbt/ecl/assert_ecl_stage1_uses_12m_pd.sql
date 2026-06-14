select
    loan_id,
    scenario_name,
    ifrs9_stage,
    pd_horizon
from {{ ref('mart_finance_ecl_allowance') }}
where
    ifrs9_stage = 1
    and pd_horizon = 'lifetime'
    and scenario_name != 'probability_weighted'
