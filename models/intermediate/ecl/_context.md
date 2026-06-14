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

- PD term structure uses a stationary Markov approximation: average balance-weighted
  transition rate from `mart_risk_roll_rate_matrix`, then `1 - (1 - p_step)^12` for
  12-month PD. This closed-form is equivalent to the full 12-CTE unroll under a
  time-stationary chain assumption and is preferred here to stay within the 40-line
  CTE limit (engineering-principles.md §2).
- Lifetime PD reads cohort-averaged terminal CDR from `mart_risk_vintage_curve`, using
  LAST_VALUE to handle censored rows at high MOB.
- Scenario variation is injected exclusively in `int_ecl_components` via cross-join to
  `ecl_scenario_weights`. Upstream intermediates are scenario-agnostic.
- EAD for Stage 3 reduces by post-default recovery already received.
- Discount factor is toggled by `ecl_include_discount_factor` var (default: false).
