-- Mart-prep intermediate. Computes Exposure at Default (EAD) per loan.
-- Grain: one row per loan_id.
--
-- Amortizing products (personal_loan, auto_loan, mortgage):
--   EAD = ending_balance_amount from the latest fct_payment row (ccf_rate = 0.00).
--
-- Credit card:
--   EAD = ending_balance_amount + ccf_rate * (credit_limit_amount - ending_balance_amount)
--   Undrawn commitment scaled by Credit Conversion Factor (Basel II retail revolving, 0.75).
--
-- Stage 3 loans: EAD is reduced by cumulative recovery_amount received after default_month.
-- For loans defaulted within the recovery_lag_months window, recovery_amount = 0 and EAD
-- equals the full ending_balance_amount.

{{ config(materialized='view') }}

with ead_params as (
    select
        ecl_ead_parameters.product_type,
        ecl_ead_parameters.ccf_rate
    from {{ ref('ecl_ead_parameters') }} as ecl_ead_parameters
),

loan_attrs as (
    select
        dim_loan.loan_id,
        dim_loan.credit_limit_amount,
        dim_loan.is_amortizing
    from {{ ref('dim_loan') }} as dim_loan
),

latest_mob_per_loan as (
    select
        fct_payment.loan_id,
        max(fct_payment.months_on_book) as latest_mob
    from {{ ref('fct_payment') }} as fct_payment
    group by fct_payment.loan_id
),

latest_payment as (
    select
        fct_payment.loan_id,
        fct_payment.product_type,
        fct_payment.report_month as as_of_date,
        fct_payment.ending_balance_amount,
        fct_payment.months_on_book
    from {{ ref('fct_payment') }} as fct_payment
    inner join latest_mob_per_loan
        on
            fct_payment.loan_id = latest_mob_per_loan.loan_id
            and fct_payment.months_on_book = latest_mob_per_loan.latest_mob
),

defaulted_loans as (
    select
        fct_loan_lifecycle.loan_id,
        fct_loan_lifecycle.default_month
    from {{ ref('fct_loan_lifecycle') }} as fct_loan_lifecycle
    where fct_loan_lifecycle.default_month is not null
),

post_default_payments as (
    select
        fct_payment.loan_id,
        sum(fct_payment.recovery_amount) as total_recovery_amount
    from {{ ref('fct_payment') }} as fct_payment
    inner join defaulted_loans
        on
            fct_payment.loan_id = defaulted_loans.loan_id
            and fct_payment.report_month > defaulted_loans.default_month
    group by fct_payment.loan_id
),

ead_inputs as (
    select
        latest_payment.loan_id,
        latest_payment.product_type,
        latest_payment.as_of_date,
        latest_payment.ending_balance_amount,
        loan_attrs.credit_limit_amount,
        loan_attrs.is_amortizing,
        ead_params.ccf_rate,
        coalesce(post_default_payments.total_recovery_amount, 0.0) as recovery_received
    from latest_payment
    inner join loan_attrs
        on latest_payment.loan_id = loan_attrs.loan_id
    inner join ead_params
        on latest_payment.product_type = ead_params.product_type
    left join post_default_payments
        on latest_payment.loan_id = post_default_payments.loan_id
)

select
    ead_inputs.loan_id,
    ead_inputs.as_of_date,
    ead_inputs.product_type,
    ead_inputs.ending_balance_amount,
    ead_inputs.ccf_rate,
    ead_inputs.recovery_received,
    cast(
        greatest(
            0.0,
            case
                when ead_inputs.is_amortizing
                    then ead_inputs.ending_balance_amount - ead_inputs.recovery_received
                else
                    ead_inputs.ending_balance_amount
                    + ead_inputs.ccf_rate * (
                        coalesce(ead_inputs.credit_limit_amount, 0.0)
                        - ead_inputs.ending_balance_amount
                    )
                    - ead_inputs.recovery_received
            end
        ) as decimal(18, 6)
    ) as ead_amount
from ead_inputs
