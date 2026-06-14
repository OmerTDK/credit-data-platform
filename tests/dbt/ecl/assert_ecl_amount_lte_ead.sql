select
    loan_id,
    scenario_name,
    ecl_amount,
    ead_amount
from {{ ref('mart_finance_ecl_allowance') }}
where
    ecl_amount > ead_amount
    and scenario_name != 'probability_weighted'
