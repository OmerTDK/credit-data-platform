select
    loan_id,
    scenario_name,
    pd_rate
from {{ ref('mart_finance_ecl_allowance') }}
where
    scenario_name != 'probability_weighted'
    and (pd_rate < 0 or pd_rate > 1.0)
