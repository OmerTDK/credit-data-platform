-- Mart-prep intermediate. Reads DWH facts/dimensions and risk marts to build
-- ECL-specific PD term structure for downstream mart_finance_ecl_* marts.

{{ config(materialized='view') }}

with constants as (
    select 12 as markov_step_count
),

delinquency_buckets as (
    select 'current' as bucket
    union all
    select 'dpd_30' as bucket
    union all
    select 'dpd_60' as bucket
    union all
    select 'dpd_90_plus' as bucket
),

all_segments as (
    select distinct
        mart_risk_roll_rate_matrix.product_type,
        mart_risk_roll_rate_matrix.score_band
    from {{ ref('mart_risk_roll_rate_matrix') }} as mart_risk_roll_rate_matrix
    where mart_risk_roll_rate_matrix.transition_balance_rate is not null
),

segment_bucket_spine as (
    select
        all_segments.product_type,
        all_segments.score_band,
        delinquency_buckets.bucket as starting_bucket
    from all_segments
    cross join delinquency_buckets
),

default_step_rates as (
    select
        mart_risk_roll_rate_matrix.product_type,
        mart_risk_roll_rate_matrix.score_band,
        mart_risk_roll_rate_matrix.from_bucket,
        avg(mart_risk_roll_rate_matrix.transition_balance_rate) as avg_default_step_rate
    from {{ ref('mart_risk_roll_rate_matrix') }} as mart_risk_roll_rate_matrix
    where
        mart_risk_roll_rate_matrix.to_bucket = 'default'
        and mart_risk_roll_rate_matrix.transition_balance_rate is not null
    group by
        mart_risk_roll_rate_matrix.product_type,
        mart_risk_roll_rate_matrix.score_band,
        mart_risk_roll_rate_matrix.from_bucket
),

pd_12m_raw as (
    select
        segment_bucket_spine.product_type,
        segment_bucket_spine.score_band,
        segment_bucket_spine.starting_bucket,
        cast(
            greatest(
                0.0,
                least(
                    1.0,
                    coalesce(
                        1.0 - power(
                            cast(
                                1.0 - default_step_rates.avg_default_step_rate
                                as decimal(10, 8)
                            ),
                            constants.markov_step_count
                        ),
                        0.0
                    )
                )
            ) as decimal(10, 8)
        ) as pd_12m
    from segment_bucket_spine
    left join default_step_rates
        on
            segment_bucket_spine.product_type = default_step_rates.product_type
            and segment_bucket_spine.score_band = default_step_rates.score_band
            and segment_bucket_spine.starting_bucket = default_step_rates.from_bucket
    cross join constants
),

vintage_non_censored as (
    select
        mart_risk_vintage_curve.product_type,
        mart_risk_vintage_curve.score_band,
        mart_risk_vintage_curve.origination_cohort_quarter,
        mart_risk_vintage_curve.months_on_book,
        mart_risk_vintage_curve.cumulative_default_rate
    from {{ ref('mart_risk_vintage_curve') }} as mart_risk_vintage_curve
    where not mart_risk_vintage_curve.is_censored
),

last_non_censored_cdr as (
    select
        vintage_non_censored.product_type,
        vintage_non_censored.score_band,
        vintage_non_censored.origination_cohort_quarter,
        last_value(vintage_non_censored.cumulative_default_rate)
            over (
                partition by
                    vintage_non_censored.product_type,
                    vintage_non_censored.score_band,
                    vintage_non_censored.origination_cohort_quarter
                order by vintage_non_censored.months_on_book
                rows between unbounded preceding and unbounded following
            ) as terminal_cdr_rate
    from vintage_non_censored
),

cohort_terminal_cdr as (
    select distinct
        last_non_censored_cdr.product_type,
        last_non_censored_cdr.score_band,
        last_non_censored_cdr.origination_cohort_quarter,
        last_non_censored_cdr.terminal_cdr_rate
    from last_non_censored_cdr
),

avg_lifetime_pd as (
    select
        cohort_terminal_cdr.product_type,
        cohort_terminal_cdr.score_band,
        cast(avg(cohort_terminal_cdr.terminal_cdr_rate) as decimal(10, 8)) as avg_lifetime_pd
    from cohort_terminal_cdr
    group by cohort_terminal_cdr.product_type, cohort_terminal_cdr.score_band
)

select
    pd_12m_raw.product_type,
    pd_12m_raw.score_band,
    pd_12m_raw.starting_bucket,
    pd_12m_raw.pd_12m,
    cast(
        greatest(
            pd_12m_raw.pd_12m,
            coalesce(avg_lifetime_pd.avg_lifetime_pd, pd_12m_raw.pd_12m)
        ) as decimal(10, 8)
    ) as pd_lifetime
from pd_12m_raw
left join avg_lifetime_pd
    on
        pd_12m_raw.product_type = avg_lifetime_pd.product_type
        and pd_12m_raw.score_band = avg_lifetime_pd.score_band
