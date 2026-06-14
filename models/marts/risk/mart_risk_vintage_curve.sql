{{ config(
    materialized='table',
    contract={'enforced': true}
) }}

-- Grain: (origination_cohort_quarter, product_type, score_band, months_on_book).
-- Cumulative counts span the FULL original cohort at each MOB, including loans that
-- have exited fct_payment after a terminal event. Computed via cross-join of
-- (cohort x loan x MOB range) rather than the payment spine, so no loans drop out.

with originations as (
    select
        fct_loan_origination.loan_id,
        fct_loan_origination.product_type,
        fct_loan_origination.score_band,
        fct_loan_origination.origination_month,
        -- Credit cards use credit_limit_amount; amortizing use principal_amount
        cast(date_trunc(
            'quarter',
            fct_loan_origination.origination_month
        ) as date) as origination_cohort_quarter,
        fct_loan_lifecycle.total_months_on_book,
        coalesce(fct_loan_origination.principal_amount, 0)
        + coalesce(fct_loan_origination.credit_limit_amount, 0) as cohort_principal_amount,
        -- Convert milestone dates to MOBs (months since origination_month)
        case
            when fct_loan_lifecycle.default_month is not null
                then datediff(
                    'month',
                    date_trunc('month', fct_loan_origination.origination_month),
                    fct_loan_lifecycle.default_month
                )
        end as default_mob,
        case
            when fct_loan_lifecycle.prepayment_month is not null
                then datediff(
                    'month',
                    date_trunc('month', fct_loan_origination.origination_month),
                    fct_loan_lifecycle.prepayment_month
                )
        end as prepayment_mob
    from {{ ref('fct_loan_origination') }} as fct_loan_origination
    inner join {{ ref('fct_loan_lifecycle') }} as fct_loan_lifecycle
        on fct_loan_origination.loan_id = fct_loan_lifecycle.loan_id
),

cohort_sizes as (
    select
        originations.origination_cohort_quarter,
        originations.product_type,
        originations.score_band,
        count(distinct originations.loan_id) as cohort_loan_count,
        sum(originations.cohort_principal_amount) as cohort_principal,
        max(originations.total_months_on_book) as max_mob
    from originations
    group by
        originations.origination_cohort_quarter,
        originations.product_type,
        originations.score_band
),

-- All possible MOB values up to the maximum observed across any cohort.
mob_numbers as (
    select unnest(range(1, 100)) as months_on_book
),

-- Explicit MOB spine: all MOBs from 1 to the max observed for each cohort.
mob_spine as (
    select
        cohort_sizes.origination_cohort_quarter,
        cohort_sizes.product_type,
        cohort_sizes.score_band,
        mob_numbers.months_on_book
    from cohort_sizes
    cross join mob_numbers
    where mob_numbers.months_on_book <= cohort_sizes.max_mob
),

-- For each loan x MOB: has it defaulted/prepaid by this MOB?
-- No correlated subqueries: mob comparisons use pre-computed default_mob / prepayment_mob.
loan_milestone_flags as (
    select
        mob_spine.origination_cohort_quarter,
        mob_spine.product_type,
        mob_spine.score_band,
        mob_spine.months_on_book,
        cast(
            originations.default_mob is not null
            and originations.default_mob <= mob_spine.months_on_book
            as integer
        ) as has_defaulted_by_mob_flag,
        cast(
            originations.prepayment_mob is not null
            and originations.default_mob is null
            and originations.prepayment_mob <= mob_spine.months_on_book
            as integer
        ) as has_prepaid_non_defaulted_by_mob_flag
    from originations
    inner join mob_spine
        on
            originations.origination_cohort_quarter = mob_spine.origination_cohort_quarter
            and originations.product_type = mob_spine.product_type
            and originations.score_band = mob_spine.score_band
),

event_flags as (
    select
        loan_milestone_flags.origination_cohort_quarter,
        loan_milestone_flags.product_type,
        loan_milestone_flags.score_band,
        loan_milestone_flags.months_on_book,
        sum(loan_milestone_flags.has_defaulted_by_mob_flag) as cumulative_default_count,
        sum(loan_milestone_flags.has_prepaid_non_defaulted_by_mob_flag)
            as cumulative_prepayment_count
    from loan_milestone_flags
    group by
        loan_milestone_flags.origination_cohort_quarter,
        loan_milestone_flags.product_type,
        loan_milestone_flags.score_band,
        loan_milestone_flags.months_on_book
)

select
    {{ generate_surrogate_key([
        'cast(event_flags.origination_cohort_quarter as varchar)',
        'event_flags.product_type',
        'event_flags.score_band',
        'cast(event_flags.months_on_book as varchar)'
    ]) }} as vintage_curve_key,
    event_flags.origination_cohort_quarter,
    event_flags.product_type,
    event_flags.score_band,
    cast(event_flags.months_on_book as integer) as months_on_book,
    cast(cohort_sizes.cohort_loan_count as integer) as cohort_loan_count,
    cast(cohort_sizes.cohort_principal as decimal(18, 2)) as cohort_principal,
    cast(event_flags.cumulative_default_count as integer) as cumulative_default_count,
    cast(event_flags.cumulative_prepayment_count as integer) as cumulative_prepayment_count,
    cast(
        cohort_sizes.cohort_loan_count - event_flags.cumulative_default_count
        as integer
    ) as surviving_non_defaulted_count,
    cast(
        cohort_sizes.cohort_loan_count
        - event_flags.cumulative_default_count
        - event_flags.cumulative_prepayment_count
        as integer
    ) as loans_at_risk_count,
    cast(
        cast(event_flags.cumulative_default_count as double)
        / nullif(cohort_sizes.cohort_loan_count, 0)
        as decimal(10, 6)
    ) as cumulative_default_rate,
    cast(
        cast(event_flags.cumulative_prepayment_count as double)
        / nullif(
            cohort_sizes.cohort_loan_count - event_flags.cumulative_default_count,
            0
        )
        as decimal(10, 6)
    ) as cumulative_prepayment_rate,
    (
        cohort_sizes.cohort_loan_count
        - event_flags.cumulative_default_count
        - event_flags.cumulative_prepayment_count
    ) < 10 as is_censored,
    current_timestamp as _loaded_at
from event_flags
inner join cohort_sizes
    on
        event_flags.origination_cohort_quarter = cohort_sizes.origination_cohort_quarter
        and event_flags.product_type = cohort_sizes.product_type
        and event_flags.score_band = cohort_sizes.score_band
