{{ config(
    materialized='table',
    contract={'enforced': true}
) }}

with allowance as (
    select
        mart_finance_ecl_allowance.loan_id,
        mart_finance_ecl_allowance.as_of_date,
        mart_finance_ecl_allowance.ifrs9_stage,
        mart_finance_ecl_allowance.scenario_name,
        mart_finance_ecl_allowance.ead_amount,
        mart_finance_ecl_allowance.ecl_amount
    from {{ ref('mart_finance_ecl_allowance') }} as mart_finance_ecl_allowance
),

loan_attrs as (
    select
        dim_loan.loan_id,
        dim_loan.product_type,
        dim_loan.score_band
    from {{ ref('dim_loan') }} as dim_loan
),

allowance_with_attrs as (
    select
        allowance.as_of_date,
        loan_attrs.product_type,
        loan_attrs.score_band,
        allowance.ifrs9_stage,
        allowance.scenario_name,
        allowance.loan_id,
        allowance.ead_amount,
        allowance.ecl_amount
    from allowance
    inner join loan_attrs
        on allowance.loan_id = loan_attrs.loan_id
)

select
    {{ generate_surrogate_key([
        'allowance_with_attrs.as_of_date',
        'allowance_with_attrs.product_type',
        'allowance_with_attrs.score_band',
        'cast(allowance_with_attrs.ifrs9_stage as varchar)',
        'allowance_with_attrs.scenario_name'
    ]) }} as ecl_summary_key,
    allowance_with_attrs.as_of_date,
    allowance_with_attrs.product_type,
    allowance_with_attrs.score_band,
    allowance_with_attrs.ifrs9_stage,
    allowance_with_attrs.scenario_name,
    cast(count(distinct allowance_with_attrs.loan_id) as bigint) as loan_count,
    cast(sum(allowance_with_attrs.ead_amount) as decimal(18, 6)) as total_ead_amount,
    cast(sum(allowance_with_attrs.ecl_amount) as decimal(18, 6)) as total_ecl_amount,
    cast(
        sum(allowance_with_attrs.ecl_amount)
        / nullif(sum(allowance_with_attrs.ead_amount), 0.0)
        as decimal(10, 6)
    ) as coverage_rate
from allowance_with_attrs
group by
    allowance_with_attrs.as_of_date,
    allowance_with_attrs.product_type,
    allowance_with_attrs.score_band,
    allowance_with_attrs.ifrs9_stage,
    allowance_with_attrs.scenario_name
