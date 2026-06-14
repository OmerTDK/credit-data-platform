select
    loan_id,
    scenario_name,
    ifrs9_stage,
    pd_horizon
from {{ ref('mart_finance_ecl_allowance') }}
where
    ifrs9_stage in (2, 3)
    and pd_horizon = '12m'
    and scenario_name != 'probability_weighted'
