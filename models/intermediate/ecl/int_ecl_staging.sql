-- Mart-prep intermediate. Assigns IFRS 9 ECL stage per loan at the ECL reference date.
-- Stage 3: credit-impaired. Stage 2: SICR (DPD backstop OR relative-PD OR delta-PD OR watchlist). Stage 1: no SICR.

{{ config(materialized='view') }}

with constants as (
    select
        cast({{ var('ecl_sicr_pd_delta_bp') }} as double) / 10000.0
            as sicr_pd_delta_threshold,
        cast({{ var('ecl_sicr_lifetime_pd_multiple') }} as double)
            as sicr_pd_multiple
),

current_state as (
    select
        dim_loan_current_state.loan_id,
        dim_loan_current_state.current_delinquency_bucket,
        dim_loan_current_state.current_loan_status,
        dim_loan_current_state.state_as_of_month as as_of_date,
        dim_loan_current_state.is_terminal
    from {{ ref('dim_loan_current_state') }} as dim_loan_current_state
),

loan_attrs as (
    select
        dim_loan.loan_id,
        dim_loan.product_type,
        dim_loan.score_band,
        dim_loan.origination_month,
        dim_loan.term_months,
        dim_loan.interest_rate,
        dim_loan.credit_limit_amount
    from {{ ref('dim_loan') }} as dim_loan
),

lifecycle as (
    select
        fct_loan_lifecycle.loan_id,
        fct_loan_lifecycle.final_status,
        fct_loan_lifecycle.final_balance_amount,
        fct_loan_lifecycle.total_months_on_book
    from {{ ref('fct_loan_lifecycle') }} as fct_loan_lifecycle
),

pd_term_structure as (
    select
        int_ecl_pd_term_structure.product_type,
        int_ecl_pd_term_structure.score_band,
        int_ecl_pd_term_structure.starting_bucket,
        int_ecl_pd_term_structure.pd_12m,
        int_ecl_pd_term_structure.pd_lifetime
    from {{ ref('int_ecl_pd_term_structure') }} as int_ecl_pd_term_structure
),

origination_pd as (
    select
        pd_term_structure.product_type,
        pd_term_structure.score_band,
        pd_term_structure.pd_lifetime as origination_pd_rate
    from pd_term_structure
    where pd_term_structure.starting_bucket = 'current'
),

watchlist as (
    select loan_id
    from {{ ref('ecl_watchlist') }}
),

loan_staging as (
    select
        current_state.loan_id,
        current_state.as_of_date,
        current_state.current_delinquency_bucket,
        current_state.current_loan_status,
        current_state.is_terminal,
        loan_attrs.product_type,
        loan_attrs.score_band,
        loan_attrs.origination_month,
        loan_attrs.term_months,
        loan_attrs.interest_rate,
        loan_attrs.credit_limit_amount,
        lifecycle.final_status,
        lifecycle.final_balance_amount,
        lifecycle.total_months_on_book,
        constants.sicr_pd_delta_threshold,
        constants.sicr_pd_multiple,
        origination_pd.origination_pd_rate,
        coalesce(pd_term_structure.pd_12m, 0.0) as current_pd_12m,
        coalesce(pd_term_structure.pd_lifetime, 0.0) as current_lifetime_pd,
        watchlist.loan_id is not null as is_on_watchlist
    from current_state
    inner join loan_attrs
        on current_state.loan_id = loan_attrs.loan_id
    inner join lifecycle
        on current_state.loan_id = lifecycle.loan_id
    left join pd_term_structure
        on
            loan_attrs.product_type = pd_term_structure.product_type
            and loan_attrs.score_band = pd_term_structure.score_band
            and current_state.current_delinquency_bucket = pd_term_structure.starting_bucket
    left join origination_pd
        on
            loan_attrs.product_type = origination_pd.product_type
            and loan_attrs.score_band = origination_pd.score_band
    left join watchlist
        on current_state.loan_id = watchlist.loan_id
    cross join constants
),

stage_assignments as (
    select
        loan_staging.loan_id,
        loan_staging.as_of_date,
        loan_staging.current_delinquency_bucket,
        loan_staging.current_loan_status,
        loan_staging.is_terminal,
        loan_staging.product_type,
        loan_staging.score_band,
        loan_staging.origination_month,
        loan_staging.term_months,
        loan_staging.interest_rate,
        loan_staging.credit_limit_amount,
        loan_staging.final_status,
        loan_staging.final_balance_amount,
        loan_staging.total_months_on_book,
        loan_staging.current_pd_12m,
        loan_staging.current_lifetime_pd,
        loan_staging.origination_pd_rate,
        loan_staging.is_on_watchlist,
        loan_staging.current_delinquency_bucket in ('dpd_90_plus', 'default')
        or loan_staging.current_loan_status in ('defaulted', 'recovery_complete')
            as is_stage3,
        loan_staging.current_delinquency_bucket in ('dpd_30', 'dpd_60')
        or (
            loan_staging.origination_pd_rate > 0.0
            and loan_staging.current_lifetime_pd / loan_staging.origination_pd_rate
            > loan_staging.sicr_pd_multiple
        )
        or (
            loan_staging.current_lifetime_pd - loan_staging.origination_pd_rate
            > loan_staging.sicr_pd_delta_threshold
        )
        or loan_staging.is_on_watchlist
            as is_stage2_sicr,
        loan_staging.final_status = 'paid_off'
        and loan_staging.final_balance_amount = 0.0
            as is_paid_off_zero_balance
    from loan_staging
)

select
    stage_assignments.loan_id,
    stage_assignments.as_of_date,
    stage_assignments.current_delinquency_bucket,
    stage_assignments.current_loan_status,
    stage_assignments.is_terminal,
    stage_assignments.product_type,
    stage_assignments.score_band,
    stage_assignments.origination_month,
    stage_assignments.term_months,
    stage_assignments.interest_rate,
    stage_assignments.credit_limit_amount,
    stage_assignments.final_status,
    stage_assignments.final_balance_amount,
    stage_assignments.total_months_on_book,
    stage_assignments.current_pd_12m,
    stage_assignments.current_lifetime_pd,
    stage_assignments.origination_pd_rate,
    stage_assignments.is_on_watchlist,
    stage_assignments.is_paid_off_zero_balance,
    case
        when stage_assignments.is_stage3 then 3
        when stage_assignments.is_stage2_sicr then 2
        else 1
    end as ifrs9_stage
from stage_assignments
