with scenario_weighted as (
    select
        mart_finance_ecl_allowance.loan_id,
        mart_finance_ecl_allowance.as_of_date,
        sum(
            mart_finance_ecl_allowance.ecl_amount * mart_finance_ecl_allowance.scenario_weight
        ) as expected_pw_ecl
    from {{ ref('mart_finance_ecl_allowance') }} as mart_finance_ecl_allowance
    where mart_finance_ecl_allowance.scenario_name in ('baseline', 'adverse', 'upside')
    group by
        mart_finance_ecl_allowance.loan_id,
        mart_finance_ecl_allowance.as_of_date
),

pw_rows as (
    select
        mart_finance_ecl_allowance.loan_id,
        mart_finance_ecl_allowance.as_of_date,
        mart_finance_ecl_allowance.ecl_amount as pw_ecl
    from {{ ref('mart_finance_ecl_allowance') }} as mart_finance_ecl_allowance
    where mart_finance_ecl_allowance.scenario_name = 'probability_weighted'
)

select
    pw_rows.loan_id,
    pw_rows.as_of_date,
    pw_rows.pw_ecl,
    scenario_weighted.expected_pw_ecl
from pw_rows
inner join scenario_weighted
    on
        pw_rows.loan_id = scenario_weighted.loan_id
        and pw_rows.as_of_date = scenario_weighted.as_of_date
where
    abs(pw_rows.pw_ecl - scenario_weighted.expected_pw_ecl) > 0.01
