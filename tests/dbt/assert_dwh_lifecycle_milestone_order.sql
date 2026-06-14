select
    loan_id,
    first_dpd30_month,
    first_dpd60_month,
    first_dpd90_month,
    default_month
from {{ ref('fct_loan_lifecycle') }}
where
    (
        first_dpd60_month is not null
        and first_dpd30_month is not null
        and first_dpd60_month < first_dpd30_month
    )
    or (
        first_dpd90_month is not null
        and first_dpd60_month is not null
        and first_dpd90_month < first_dpd60_month
    )
    or (
        default_month is not null
        and first_dpd90_month is not null
        and default_month < first_dpd90_month
    )
