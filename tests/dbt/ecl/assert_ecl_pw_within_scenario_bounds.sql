with per_scenario as (
    select
        loan_id,
        as_of_date,
        min(ecl_amount) as min_scenario_ecl,
        max(ecl_amount) as max_scenario_ecl
    from {{ ref('mart_finance_ecl_allowance') }}
    where scenario_name in ('baseline', 'adverse', 'upside')
    group by loan_id, as_of_date
),

pw_rows as (
    select
        loan_id,
        as_of_date,
        ecl_amount as pw_ecl
    from {{ ref('mart_finance_ecl_allowance') }}
    where scenario_name = 'probability_weighted'
)

select
    pw_rows.loan_id,
    pw_rows.as_of_date,
    pw_rows.pw_ecl,
    per_scenario.min_scenario_ecl,
    per_scenario.max_scenario_ecl
from pw_rows
inner join per_scenario
    on
        pw_rows.loan_id = per_scenario.loan_id
        and pw_rows.as_of_date = per_scenario.as_of_date
where
    pw_rows.pw_ecl < per_scenario.min_scenario_ecl - 0.000001
    or pw_rows.pw_ecl > per_scenario.max_scenario_ecl + 0.000001
