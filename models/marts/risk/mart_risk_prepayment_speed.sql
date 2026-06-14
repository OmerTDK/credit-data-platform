{{ config(
    materialized='table',
    contract={'enforced': true}
) }}

with constants as (
    select 12 as months_per_year
),

spine as (
    select
        loan_id,
        origination_cohort_quarter,
        product_type,
        months_on_book,
        beginning_balance_amount,
        unscheduled_principal,
        is_prepayment,
        loan_status,
        is_amortizing
    from {{ ref('int_risk_vintage_cohort_spine') }}
    where is_amortizing
),

pool_metrics as (
    select
        spine.origination_cohort_quarter,
        spine.product_type,
        spine.months_on_book,
        sum(
            case
                when spine.loan_status = 'active' and not spine.is_prepayment
                    then spine.beginning_balance_amount
                else 0
            end
        ) as performing_pool_balance,
        sum(spine.unscheduled_principal) as prepaid_balance,
        count(
            distinct case
                when spine.loan_status = 'active' and not spine.is_prepayment
                    then spine.loan_id
            end
        ) as eligible_loan_count,
        count(
            distinct case
                when spine.is_prepayment then spine.loan_id
            end
        ) as prepaying_loan_count
    from spine
    group by
        spine.origination_cohort_quarter,
        spine.product_type,
        spine.months_on_book
)

select
    {{ generate_surrogate_key([
        'cast(pool_metrics.origination_cohort_quarter as varchar)',
        'pool_metrics.product_type',
        'cast(pool_metrics.months_on_book as varchar)'
    ]) }}                                                               as prepayment_speed_key,
    pool_metrics.origination_cohort_quarter,
    pool_metrics.product_type,
    pool_metrics.months_on_book,
    cast(pool_metrics.performing_pool_balance as decimal(18, 2)) as performing_pool_balance,
    cast(pool_metrics.prepaid_balance as decimal(18, 2)) as prepaid_balance,
    pool_metrics.eligible_loan_count,
    pool_metrics.prepaying_loan_count,
    cast(
        cast(pool_metrics.prepaid_balance as double)
        / nullif(pool_metrics.performing_pool_balance, 0)
        as decimal(10, 6)
    ) as smm_rate,
    case
        when pool_metrics.performing_pool_balance = 0 then null
        else cast(
            1.0 - power(
                1.0 - cast(pool_metrics.prepaid_balance as double)
                / nullif(pool_metrics.performing_pool_balance, 0),
                constants.months_per_year
            )
            as decimal(10, 6)
        )
    end as cpr_rate,
    current_timestamp as _loaded_at
from pool_metrics
cross join constants
