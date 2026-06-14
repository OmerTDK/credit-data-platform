with loan_summary as (
    select
        loan_id,
        sum(principal_paid_amount) as total_principal_paid,
        sum(principal_writeoff_amount) as total_principal_writeoff
    from {{ ref('fct_payment') }}
    group by loan_id
),

origination as (
    select
        loan_id,
        principal_amount
    from {{ ref('fct_loan_origination') }}
    where product_type != 'credit_card'
),

check_amortizing as (
    select
        loan_summary.loan_id,
        origination.principal_amount,
        loan_summary.total_principal_paid + loan_summary.total_principal_writeoff as total_resolved,
        abs(
            origination.principal_amount
            - (loan_summary.total_principal_paid + loan_summary.total_principal_writeoff)
        ) as discrepancy_amount
    from loan_summary
    inner join origination
        on loan_summary.loan_id = origination.loan_id
),

completed_loans as (
    select loan_id
    from {{ ref('fct_loan_lifecycle') }}
    where
        final_status in ('paid_off', 'defaulted', 'recovery_complete')
        and product_type != 'credit_card'
)

select
    check_amortizing.loan_id,
    check_amortizing.principal_amount,
    check_amortizing.total_resolved,
    check_amortizing.discrepancy_amount
from check_amortizing
inner join completed_loans
    on check_amortizing.loan_id = completed_loans.loan_id
where check_amortizing.discrepancy_amount > 0.02
