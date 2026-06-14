# ECL intermediate — mart-prep sub-type

Models in this folder are **mart-prep intermediates** (see `standards/dbt-standards.md`
"Intermediate sub-type: mart-prep intermediate").

They read directly from DWH facts/dimensions (`dwh.*`) and risk marts (`mart_risk.*`)
to build ECL-domain projections feeding `mart_finance_ecl_*` downstream. This is
intentional and documented — it is NOT a layer-boundary breach.

## Models in this folder

| File | Feeds | Grain |
|------|-------|-------|
| `int_ecl_pd_term_structure.sql` | `int_ecl_staging`, `int_ecl_components` | (product_type, score_band, starting_bucket) |
| `int_ecl_staging.sql` | `int_ecl_components` | (loan_id) — one row per active loan |
| `int_ecl_ead_by_loan.sql` | `int_ecl_components` | (loan_id) |
| `int_ecl_lgd_by_loan.sql` | `int_ecl_components` | (loan_id) |
| `int_ecl_components.sql` | `mart_finance_ecl_allowance` | (loan_id, scenario_name) |

## Design decisions

- PD term structure runs an explicit 5-state Markov chain (`default` absorbing) over
  the count-based, row-normalised one-step transitions from `mart_risk_roll_rate_matrix`.
  A recursive CTE propagates the bucket-distribution vector; the default mass at step 12
  is the 12-month PD and at step 120 the Markov lifetime PD. A single-step
  `1 - (1 - p_step)^12` was rejected — it is zero for any bucket with no direct
  one-step transition to `default` (every bucket but `dpd_90_plus`), which would zero
  out Stage 1/2 ECL. See ADR-0007.
- Lifetime PD is the worst-case of the Markov lifetime PD, the cohort-averaged terminal
  CDR from `mart_risk_vintage_curve` (LAST_VALUE over non-censored rows), and the
  12-month PD floor.
- Scenario variation is injected exclusively in `int_ecl_components` via cross-join to
  `ecl_scenario_weights`. Upstream intermediates are scenario-agnostic.
- EAD for Stage 3 reduces by post-default recovery already received.
- Discount factor is toggled by `ecl_include_discount_factor` var (default: false).
