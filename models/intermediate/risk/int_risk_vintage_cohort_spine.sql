-- Mart-prep intermediate. Reads DWH facts/dimensions to build risk-specific
-- projection for downstream mart_risk_prepayment_speed mart.
-- Per-loan-per-MOB spine with payment attributes and unscheduled principal.

{{ config(materialized='view') }}

with originations as (
    select
        fct_loan_origination.loan_id,
        fct_loan_origination.product_type,
        fct_loan_origination.score_band,
        fct_loan_origination.principal_amount,
        fct_loan_origination.origination_month,
        cast(
            case
                when '{{ var("vintage_cohort_granularity", "quarter") }}' = 'month'
                    then date_trunc('month', fct_loan_origination.origination_month)
                else date_trunc('quarter', fct_loan_origination.origination_month)
            end
            as date
        ) as origination_cohort_quarter,
        dim_loan.is_amortizing
    from {{ ref('fct_loan_origination') }} as fct_loan_origination
    inner join {{ ref('dim_loan') }} as dim_loan
        on fct_loan_origination.loan_id = dim_loan.loan_id
),

payment_months as (
    select
        fct_payment.loan_id,
        fct_payment.months_on_book,
        fct_payment.report_month,
        fct_payment.beginning_balance_amount,
        fct_payment.ending_balance_amount,
        fct_payment.scheduled_payment_amount,
        fct_payment.actual_payment_amount,
        fct_payment.is_prepayment,
        fct_payment.loan_status,
        greatest(
            fct_payment.actual_payment_amount - fct_payment.scheduled_payment_amount,
            0
        ) * cast(fct_payment.is_prepayment as integer) as unscheduled_principal
    from {{ ref('fct_payment') }} as fct_payment
)

select
    originations.loan_id,
    originations.origination_cohort_quarter,
    originations.product_type,
    originations.score_band,
    originations.is_amortizing,
    originations.principal_amount,
    payment_months.months_on_book,
    payment_months.report_month,
    payment_months.beginning_balance_amount,
    payment_months.ending_balance_amount,
    payment_months.scheduled_payment_amount,
    payment_months.actual_payment_amount,
    payment_months.is_prepayment,
    payment_months.loan_status,
    payment_months.unscheduled_principal
from originations
inner join payment_months
    on originations.loan_id = payment_months.loan_id
