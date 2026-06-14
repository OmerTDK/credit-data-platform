-- Mart-prep intermediate. PD term structure per (product_type, score_band,
-- starting_bucket) derived from the roll-rate Markov chain and vintage curve.

{{ config(materialized='view') }}

with recursive constants as (
    select
        12 as horizon_12m_steps,
        120 as horizon_lifetime_steps
),

-- One-step, count-based transition probabilities aggregated across all
-- observation periods. Counts (not balances) give a loan-level PD. Cells with
-- to_bucket = 'default' only exist for from_bucket = 'dpd_90_plus', so a single
-- step is never enough to reach default from 'current' / 'dpd_30' / 'dpd_60':
-- the multi-step chain below is what propagates risk through the buckets.
transition_counts as (
    select
        mart_risk_roll_rate_matrix.product_type,
        mart_risk_roll_rate_matrix.score_band,
        mart_risk_roll_rate_matrix.from_bucket,
        mart_risk_roll_rate_matrix.to_bucket,
        sum(mart_risk_roll_rate_matrix.transition_loan_count) as transition_loan_count,
        sum(mart_risk_roll_rate_matrix.at_risk_loan_count) as at_risk_loan_count
    from {{ ref('mart_risk_roll_rate_matrix') }} as mart_risk_roll_rate_matrix
    group by
        mart_risk_roll_rate_matrix.product_type,
        mart_risk_roll_rate_matrix.score_band,
        mart_risk_roll_rate_matrix.from_bucket,
        mart_risk_roll_rate_matrix.to_bucket
),

-- Row-normalise so each from_bucket's outgoing probabilities sum to 1.0. The
-- raw count ratios can fall short of 1.0 because of right-censoring (loans that
-- pay off or reach period end); re-basing on the observed mass keeps the chain
-- a valid stochastic matrix.
row_totals as (
    select
        transition_counts.product_type,
        transition_counts.score_band,
        transition_counts.from_bucket,
        sum(transition_counts.transition_loan_count) as outgoing_count
    from transition_counts
    group by
        transition_counts.product_type,
        transition_counts.score_band,
        transition_counts.from_bucket
),

transition_matrix as (
    select
        transition_counts.product_type,
        transition_counts.score_band,
        transition_counts.from_bucket,
        transition_counts.to_bucket,
        cast(
            transition_counts.transition_loan_count
            / nullif(row_totals.outgoing_count, 0)
            as double
        ) as step_probability
    from transition_counts
    inner join row_totals
        on
            transition_counts.product_type = row_totals.product_type
            and transition_counts.score_band = row_totals.score_band
            and transition_counts.from_bucket = row_totals.from_bucket
    where transition_counts.transition_loan_count > 0
),

segments as (
    select distinct
        transition_matrix.product_type,
        transition_matrix.score_band
    from transition_matrix
),

-- Augment the matrix with the absorbing default self-loop so the recursive
-- step is a plain join (no correlated lateral): mass in 'default' stays there.
transition_matrix_absorbing as (
    select
        transition_matrix.product_type,
        transition_matrix.score_band,
        transition_matrix.from_bucket,
        transition_matrix.to_bucket,
        transition_matrix.step_probability
    from transition_matrix

    union all

    select
        segments.product_type,
        segments.score_band,
        'default' as from_bucket,
        'default' as to_bucket,
        cast(1.0 as double) as step_probability
    from segments
),

starting_buckets as (
    select 'current' as starting_bucket
    union all
    select 'dpd_30' as starting_bucket
    union all
    select 'dpd_60' as starting_bucket
    union all
    select 'dpd_90_plus' as starting_bucket
),

-- Recursive Markov propagation. Each row is a probability-mass vector entry:
-- "starting in `starting_bucket`, after `step` transitions, this much mass sits
-- in `current_bucket`." `default` is absorbing — mass that reaches it stays.
markov_state (
    product_type, score_band, starting_bucket, current_bucket, probability, step
) as (
    select
        segments.product_type,
        segments.score_band,
        starting_buckets.starting_bucket,
        starting_buckets.starting_bucket as current_bucket,
        cast(1.0 as double) as probability,
        0 as step
    from segments
    cross join starting_buckets

    union all

    -- 120 is horizon_lifetime_steps; a recursive term cannot reference the
    -- constants CTE, so the lifetime horizon is inlined here as a literal.
    select
        markov_state.product_type,
        markov_state.score_band,
        markov_state.starting_bucket,
        transition_matrix_absorbing.to_bucket as current_bucket,
        sum(
            markov_state.probability * transition_matrix_absorbing.step_probability
        ) as probability,
        markov_state.step + 1 as step
    from markov_state
    inner join transition_matrix_absorbing
        on
            markov_state.product_type = transition_matrix_absorbing.product_type
            and markov_state.score_band = transition_matrix_absorbing.score_band
            and markov_state.current_bucket = transition_matrix_absorbing.from_bucket
    where markov_state.step < 120
    group by
        markov_state.product_type,
        markov_state.score_band,
        markov_state.starting_bucket,
        transition_matrix_absorbing.to_bucket,
        markov_state.step
),

default_mass as (
    select
        markov_state.product_type,
        markov_state.score_band,
        markov_state.starting_bucket,
        markov_state.step,
        markov_state.probability as default_probability
    from markov_state
    cross join constants
    where
        markov_state.current_bucket = 'default'
        and markov_state.step in (constants.horizon_12m_steps, constants.horizon_lifetime_steps)
),

pd_12m_by_segment as (
    select
        default_mass.product_type,
        default_mass.score_band,
        default_mass.starting_bucket,
        cast(
            greatest(0.0, least(1.0, max(default_mass.default_probability)))
            as decimal(10, 8)
        ) as pd_12m
    from default_mass
    cross join constants
    where default_mass.step = constants.horizon_12m_steps
    group by
        default_mass.product_type,
        default_mass.score_band,
        default_mass.starting_bucket
),

pd_markov_lifetime_by_segment as (
    select
        default_mass.product_type,
        default_mass.score_band,
        default_mass.starting_bucket,
        cast(
            greatest(0.0, least(1.0, max(default_mass.default_probability)))
            as decimal(10, 8)
        ) as pd_markov_lifetime
    from default_mass
    cross join constants
    where default_mass.step = constants.horizon_lifetime_steps
    group by
        default_mass.product_type,
        default_mass.score_band,
        default_mass.starting_bucket
),

-- Empirical lifetime PD: cohort-averaged terminal cumulative default rate from
-- the vintage curve, restricted to fully-observed (non-censored) cohort points.
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

cohort_terminal_cdr as (
    select distinct
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

vintage_lifetime_pd as (
    select
        cohort_terminal_cdr.product_type,
        cohort_terminal_cdr.score_band,
        cast(avg(cohort_terminal_cdr.terminal_cdr_rate) as decimal(10, 8)) as vintage_lifetime_pd
    from cohort_terminal_cdr
    group by cohort_terminal_cdr.product_type, cohort_terminal_cdr.score_band
)

select
    pd_12m_by_segment.product_type,
    pd_12m_by_segment.score_band,
    pd_12m_by_segment.starting_bucket,
    pd_12m_by_segment.pd_12m,
    -- Lifetime PD is the worst-case of the multi-step Markov horizon, the
    -- empirical vintage terminal CDR, and the 12-month PD floor. Vintage CDR is
    -- measured from origination ('current'); it informs every starting bucket
    -- as a lower bound but never pulls a delinquent bucket below its Markov PD.
    cast(
        greatest(
            pd_12m_by_segment.pd_12m,
            coalesce(pd_markov_lifetime_by_segment.pd_markov_lifetime, pd_12m_by_segment.pd_12m),
            coalesce(vintage_lifetime_pd.vintage_lifetime_pd, 0.0)
        ) as decimal(10, 8)
    ) as pd_lifetime
from pd_12m_by_segment
left join pd_markov_lifetime_by_segment
    on
        pd_12m_by_segment.product_type = pd_markov_lifetime_by_segment.product_type
        and pd_12m_by_segment.score_band = pd_markov_lifetime_by_segment.score_band
        and pd_12m_by_segment.starting_bucket = pd_markov_lifetime_by_segment.starting_bucket
left join vintage_lifetime_pd
    on
        pd_12m_by_segment.product_type = vintage_lifetime_pd.product_type
        and pd_12m_by_segment.score_band = vintage_lifetime_pd.score_band
