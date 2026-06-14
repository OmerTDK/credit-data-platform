{{ config(
    materialized='table',
    contract={'enforced': true}
) }}

with scenario_rows as (
    select
        int_ecl_components.loan_id,
        int_ecl_components.as_of_date,
        int_ecl_components.ifrs9_stage,
        int_ecl_components.scenario_name,
        int_ecl_components.scenario_weight,
        int_ecl_components.pd_rate,
        int_ecl_components.pd_horizon,
        int_ecl_components.lgd_rate,
        int_ecl_components.ead_amount,
        int_ecl_components.discount_factor,
        int_ecl_components.ecl_amount,
        int_ecl_components.is_terminal
    from {{ ref('int_ecl_components') }} as int_ecl_components
),

probability_weighted as (
    select
        scenario_rows.loan_id,
        scenario_rows.as_of_date,
        scenario_rows.ifrs9_stage,
        'probability_weighted' as scenario_name,
        cast(1.0 as decimal(10, 8)) as scenario_weight,
        cast(
            sum(scenario_rows.pd_rate * scenario_rows.scenario_weight) as decimal(10, 8)
        ) as pd_rate,
        cast(
            sum(scenario_rows.lgd_rate * scenario_rows.scenario_weight) as decimal(10, 8)
        ) as lgd_rate,
        cast(
            sum(scenario_rows.discount_factor * scenario_rows.scenario_weight) as decimal(10, 8)
        ) as discount_factor,
        cast(
            sum(scenario_rows.ecl_amount * scenario_rows.scenario_weight) as decimal(18, 6)
        ) as ecl_amount,
        max(scenario_rows.pd_horizon) as pd_horizon,
        max(scenario_rows.ead_amount) as ead_amount,
        max(cast(scenario_rows.is_terminal as integer)) = 1 as is_terminal
    from scenario_rows
    group by
        scenario_rows.loan_id,
        scenario_rows.as_of_date,
        scenario_rows.ifrs9_stage
)

select
    loan_id,
    as_of_date,
    ifrs9_stage,
    scenario_name,
    cast(scenario_weight as decimal(10, 8)) as scenario_weight,
    cast(pd_rate as decimal(10, 8)) as pd_rate,
    cast(pd_horizon as varchar) as pd_horizon,
    cast(lgd_rate as decimal(10, 8)) as lgd_rate,
    cast(ead_amount as decimal(18, 6)) as ead_amount,
    cast(discount_factor as decimal(10, 8)) as discount_factor,
    cast(ecl_amount as decimal(18, 6)) as ecl_amount,
    cast(is_terminal as boolean) as is_terminal
from scenario_rows

union all

select
    loan_id,
    as_of_date,
    ifrs9_stage,
    scenario_name,
    cast(scenario_weight as decimal(10, 8)) as scenario_weight,
    cast(pd_rate as decimal(10, 8)) as pd_rate,
    cast(pd_horizon as varchar) as pd_horizon,
    cast(lgd_rate as decimal(10, 8)) as lgd_rate,
    cast(ead_amount as decimal(18, 6)) as ead_amount,
    cast(discount_factor as decimal(10, 8)) as discount_factor,
    cast(ecl_amount as decimal(18, 6)) as ecl_amount,
    cast(is_terminal as boolean) as is_terminal
from probability_weighted
