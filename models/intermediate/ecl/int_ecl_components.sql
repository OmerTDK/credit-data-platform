-- Mart-prep intermediate. Reads DWH facts/dimensions and risk marts to build
-- ECL-specific component inputs (PD, LGD, EAD, discount factor) for downstream mart_finance_ecl_* marts.

{{ config(materialized='view') }}

with constants as (
    select
        cast({{ var('ecl_credit_card_behavioural_maturity_months') }} as integer)
            as credit_card_term_months,
        cast({{ var('ecl_include_discount_factor') }} as boolean)
            as include_discount_factor,
        6 as stage1_horizon_months,
        12.0 as months_per_year
),

staging as (
    select
        int_ecl_staging.loan_id,
        int_ecl_staging.as_of_date,
        int_ecl_staging.ifrs9_stage,
        int_ecl_staging.current_pd_12m,
        int_ecl_staging.current_lifetime_pd,
        int_ecl_staging.term_months,
        int_ecl_staging.total_months_on_book,
        int_ecl_staging.interest_rate,
        int_ecl_staging.is_terminal,
        int_ecl_staging.is_paid_off_zero_balance
    from {{ ref('int_ecl_staging') }} as int_ecl_staging
),

lgd as (
    select
        int_ecl_lgd_by_loan.loan_id,
        int_ecl_lgd_by_loan.base_lgd_rate
    from {{ ref('int_ecl_lgd_by_loan') }} as int_ecl_lgd_by_loan
),

ead as (
    select
        int_ecl_ead_by_loan.loan_id,
        int_ecl_ead_by_loan.ead_amount
    from {{ ref('int_ecl_ead_by_loan') }} as int_ecl_ead_by_loan
),

scenarios as (
    select
        ecl_scenario_weights.scenario_name,
        ecl_scenario_weights.scenario_weight,
        ecl_scenario_weights.pd_scalar,
        ecl_scenario_weights.lgd_scalar
    from {{ ref('ecl_scenario_weights') }} as ecl_scenario_weights
),

loan_scenario_grid as (
    select
        staging.loan_id,
        staging.as_of_date,
        staging.ifrs9_stage,
        staging.current_pd_12m,
        staging.current_lifetime_pd,
        staging.term_months,
        staging.total_months_on_book,
        staging.interest_rate,
        staging.is_terminal,
        staging.is_paid_off_zero_balance,
        lgd.base_lgd_rate,
        ead.ead_amount,
        scenarios.scenario_name,
        scenarios.scenario_weight,
        scenarios.pd_scalar,
        scenarios.lgd_scalar,
        constants.credit_card_term_months,
        constants.include_discount_factor,
        constants.stage1_horizon_months,
        constants.months_per_year
    from staging
    inner join lgd
        on staging.loan_id = lgd.loan_id
    inner join ead
        on staging.loan_id = ead.loan_id
    cross join scenarios
    cross join constants
),

ecl_computed as (
    select
        loan_scenario_grid.loan_id,
        loan_scenario_grid.as_of_date,
        loan_scenario_grid.ifrs9_stage,
        loan_scenario_grid.scenario_name,
        loan_scenario_grid.scenario_weight,
        loan_scenario_grid.ead_amount,
        loan_scenario_grid.is_terminal,
        loan_scenario_grid.is_paid_off_zero_balance,
        cast(
            case
                when loan_scenario_grid.ifrs9_stage = 1
                    then '12m'
                else 'lifetime'
            end
            as varchar
        ) as pd_horizon,
        cast(
            case
                when loan_scenario_grid.ifrs9_stage = 3
                    then 1.0
                when loan_scenario_grid.ifrs9_stage = 2
                    then greatest(
                        0.0,
                        least(
                            1.0,
                            loan_scenario_grid.current_lifetime_pd
                            * loan_scenario_grid.pd_scalar
                        )
                    )
                else
                    greatest(
                        0.0,
                        least(
                            1.0,
                            loan_scenario_grid.current_pd_12m * loan_scenario_grid.pd_scalar
                        )
                    )
            end as decimal(10, 8)
        ) as pd_rate,
        cast(
            greatest(
                0.0,
                least(
                    1.0,
                    loan_scenario_grid.base_lgd_rate * loan_scenario_grid.lgd_scalar
                )
            ) as decimal(10, 8)
        ) as lgd_rate,
        cast(
            case
                when not loan_scenario_grid.include_discount_factor
                    then 1.0
                when loan_scenario_grid.ifrs9_stage = 1
                    then 1.0 / power(
                        cast(
                            1.0 + loan_scenario_grid.interest_rate
                            / loan_scenario_grid.months_per_year as decimal(10, 8)
                        ),
                        loan_scenario_grid.stage1_horizon_months
                    )
                else
                    1.0 / power(
                        cast(
                            1.0 + loan_scenario_grid.interest_rate
                            / loan_scenario_grid.months_per_year as decimal(10, 8)
                        ),
                        cast(
                            greatest(
                                1,
                                coalesce(
                                    loan_scenario_grid.term_months,
                                    loan_scenario_grid.credit_card_term_months
                                ) - loan_scenario_grid.total_months_on_book
                            ) as double
                        ) / 2.0
                    )
            end as decimal(10, 8)
        ) as discount_factor
    from loan_scenario_grid
)

select
    ecl_computed.loan_id,
    ecl_computed.as_of_date,
    ecl_computed.ifrs9_stage,
    ecl_computed.scenario_name,
    ecl_computed.scenario_weight,
    ecl_computed.pd_rate,
    ecl_computed.pd_horizon,
    ecl_computed.lgd_rate,
    ecl_computed.ead_amount,
    ecl_computed.discount_factor,
    cast(
        case
            when ecl_computed.is_paid_off_zero_balance
                then 0.0
            else
                ecl_computed.pd_rate
                * ecl_computed.lgd_rate
                * ecl_computed.ead_amount
                * ecl_computed.discount_factor
        end as decimal(18, 6)
    ) as ecl_amount,
    ecl_computed.is_terminal
from ecl_computed
