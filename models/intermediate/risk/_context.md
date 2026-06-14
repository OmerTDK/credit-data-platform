# Risk intermediate — mart-prep sub-type

Models in this folder are **mart-prep intermediates** (see `standards/dbt-standards.md` §
"Intermediate sub-type: mart-prep intermediate").

They read directly from DWH facts and dimensions (`dwh.*`) to build risk-domain projections
that feed `mart_risk.*` downstream. This is intentional and documented — it is NOT a
layer-boundary breach.

## Models in this folder

| File | Feeds | Grain |
|------|-------|-------|
| `int_risk_roll_rate_observations.sql` | `mart_risk_roll_rate_matrix` | (product_type, score_band, observation_period, from_bucket, to_bucket) |
| `int_risk_vintage_cohort_spine.sql` | `mart_risk_prepayment_speed` | (loan_id, origination_cohort_quarter, months_on_book) |

Note: `mart_risk_vintage_curve` does NOT use the cohort spine. It computes cumulative default
and prepayment counts via an explicit (loan × MOB range) cross-join anchored directly to
`fct_loan_origination` and `fct_loan_lifecycle`. This is intentional — the payment spine would
cause exited loans to drop out of cumulative counts (see ADR-0006 §2).

## Why here and not inside the mart CTEs

Both intermediates aggregate or join across at least three DWH tables. Embedding that logic
inside a mart CTE would produce models exceeding 80 lines per CTE block (violating
`engineering-principles.md` §2). The roll-rate intermediate handles the shifted-denominator
join logic, and the cohort spine handles the per-loan-per-MOB projection for prepayment speed,
avoiding a redundant full scan of `fct_payment` if both were computed inline.
