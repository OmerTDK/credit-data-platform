# ADR-0007: IFRS 9 ECL Methodology

**Status:** Accepted
**Date:** 2026-06-14
**Phase:** 4

---

## Context

Phase 4 adds the IFRS 9 Expected Credit Loss (ECL) layer to the platform. The
platform already has a complete DWH (dim_loan, fct_payment, fct_loan_lifecycle,
dim_loan_current_state, fct_loan_state_event) and risk marts
(mart_risk_roll_rate_matrix, mart_risk_vintage_curve, mart_risk_prepayment_speed).

The ECL layer must:

1. Assign IFRS 9 Stage (1, 2, 3) per loan with an explicit SICR trigger.
2. Compute 12-month ECL for Stage 1, lifetime ECL for Stage 2/3.
3. Source PD, LGD, EAD from parameterized seeds and risk marts — not a fitted model.
4. Support multiple macro scenarios with probability weights.
5. Be backtested against realized losses on the synthetic history.
6. Have enforced dbt contracts on the two mart_finance models.
7. Be wired into CI through a pytest fixture that calls dbt via subprocess.

---

## Decision: Stationary Markov approximation for 12-month PD

**The full 12-step Markov CTE unroll (one CTE per step) was evaluated and
rejected.** The verbosity required to express the 5-state × 12-step transition
matrix recursion in SQL (60+ CTEs across the full term structure) exceeds the
40-line CTE limit in `engineering-principles.md §2`, and would require splitting
into 4+ intermediates with dependency chains that obscure the logic.

**Chosen approach:** Stationary Markov closed-form.

Under the stationary assumption (time-averaged transition rates), the 12-month
cumulative PD from a given starting bucket simplifies to:

```
pd_12m = 1 - (1 - p_default_step)^12
```

where `p_default_step` is the balance-weighted average probability of transitioning
into the `default` absorbing state in one step, derived from
`mart_risk_roll_rate_matrix.transition_balance_rate`.

**Tradeoff:** The stationary assumption loses path-dependency (a loan that
moves from `current` → `dpd_30` → `current` is treated the same as one that
stays `current` throughout). For the synthetic book this is acceptable — the
generator uses a stationary transition matrix by construction, so the stationarity
assumption is exact here. On a real book with macro-driven non-stationarity,
this would understate PD in stress periods.

**Rationale for choosing `transition_balance_rate` over `transition_rate`:**
Per the Phase 3 YAML description, balance-weighted rates are preferred for ECL
PD calibration — they weight the default signal by the exposure size rather than
loan count, which is more conservative for large loans.

---

## Decision: Lifetime PD from vintage curve terminal CDR

Lifetime PD is the cohort-averaged terminal cumulative default rate from
`mart_risk_vintage_curve`. For segments near maturity where the vintage curve
is censored (fewer than 10 loans remaining observable), the last non-censored
CDR is used via `LAST_VALUE(...) OVER (ORDER BY months_on_book)`.

**Tradeoff:** The terminal CDR is a realized (backward-looking) estimate, not a
forward-looking one. For a short synthetic history (2022–2023 cohorts with
24 months max MOB), many cohorts have not yet fully seasoned. This makes the
lifetime PD estimate downward-biased for young cohorts. Mitigation: the absolute
PD delta SICR trigger (`ecl_sicr_pd_delta_bp`) adds an independent path to Stage 2
that does not depend on the vintage curve having seasoned.

---

## Decision: EAD is scenario-agnostic

EAD is a contractual/behavioral quantity (balance sheet exposure plus undrawn
commitment scaled by CCF). It does not vary by macro scenario in this implementation.
Scenario variation enters only through PD and LGD scalars.

**Tradeoff:** In a more sophisticated model, CCF for credit cards would vary by
scenario (drawdown rates increase in stress). This is a documented simplification
appropriate for a parameterized — not fitted — ECL model.

---

## Decision: Discount factor toggled off by default

IFRS 9 technically requires ECL to be discounted at the effective interest rate.
The discount factor is implemented and toggleable via `ecl_include_discount_factor`
var, but defaults to `false` (no discounting).

**Rationale:** For a synthetic book with stylized parameters and no actual market
rates, the discount factor adds precision noise without improving the signal quality
of the ECL estimate. Discount factors matter most when the expected default horizon
is long (Stage 2/3 loans, high EIR). The toggle lets a real user enable discounting
without a code change — just a var override.

---

## Decision: mart_finance uses full-refresh materialization

Both `mart_finance_ecl_allowance` and `mart_finance_ecl_summary` are materialized
as full-refresh tables, not incremental.

**Rationale:** ECL is a point-in-time stock — the entire book is re-valued at
each run date. There is no natural incremental key (unlike payment-fact rows which
are append-only). At 12,000 loans × 4 scenarios = 48,000 rows, full-refresh at
DuckDB takes < 1 second. Incremental ECL would require tracking `as_of_date` as
a surrogate for the run date and handling paid-off loans dropping off the book —
complexity with no performance benefit at this scale.

---

## Decision: Backtest in Python, not a dbt mart

The backtest iterates over 8 quarterly as_of_dates and computes modeled ECL vs.
realized losses at each date. This is a temporal loop — not expressible as
set-based SQL without materializing 8 × 12,000 = 96,000 rows of intermediate
state.

A dbt mart approach (one CTE per as_of_date) was rejected: it hardcodes the
date list into SQL, cannot dynamically iterate, and produces a model that cannot
run without a prior build of `mart_finance_ecl_allowance` at each historical date.

The Python approach reads seeds from CSV (zero warehouse dependency for parameter
validation) and DWH data from DuckDB. This keeps the backtest runnable in CI
without a live warehouse connection.

---

## Decision: Three SICR triggers applied as OR conditions

Per IFRS 9 §5.5, SICR determination must be based on a combination of
quantitative and qualitative factors. Three independent triggers are applied:

1. **Quantitative backstop (DPD >= 30):** The rebuttable presumption from
   IFRS 9 §B5.5.19, used here as a non-rebuttable floor. This fires for all
   loans in `dpd_30` or `dpd_60` buckets.

2. **Relative PD multiple:** `current_lifetime_pd / origination_lifetime_pd`
   exceeds `ecl_sicr_lifetime_pd_multiple` (default 2.0x). Captures structural
   deterioration in creditworthiness beyond delinquency.

3. **Absolute PD delta:** `current_lifetime_pd - origination_lifetime_pd`
   exceeds `ecl_sicr_pd_delta_bp / 10000` (default 200 bps). Guards against
   the relative trigger failing to fire for young cohorts whose origination
   PD is near zero (the multiple is unbounded when the denominator is tiny).

**Tradeoff:** Three triggers create some over-classification risk (loans that
are technically performing but have deteriorating PD curves may be Stage 2).
This is intentional conservatism — IFRS 9 prefers over-provisioning to under.

---

## Grain and contract documentation

| Model | Grain | Contract |
|-------|-------|---------|
| `int_ecl_pd_term_structure` | (product_type, score_band, starting_bucket) | None (intermediate view) |
| `int_ecl_staging` | (loan_id) | None (intermediate view) |
| `int_ecl_ead_by_loan` | (loan_id) | None (intermediate view) |
| `int_ecl_lgd_by_loan` | (loan_id) | None (intermediate view) |
| `int_ecl_components` | (loan_id, scenario_name) | None (intermediate view) |
| `mart_finance_ecl_allowance` | (loan_id, scenario_name) | Enforced |
| `mart_finance_ecl_summary` | (as_of_date, product_type, score_band, ifrs9_stage, scenario_name) | Enforced |

---

## Kill-test verification (required per Phase mandate)

The invariant test `assert_ecl_stage3_pd_equals_one` was kill-tested by
temporarily setting `pd_rate` to a constant 0.5 for all Stage 3 loans in
`int_ecl_components` (`then 1.0` → `then 0.5`). The test fired with **2,319
violations** (773 Stage 3 loans × 3 non-probability-weighted scenarios).
Mutation reverted; `dbt test --select assert_ecl_stage3_pd_equals_one` confirmed
1 PASS with 0 violations.

---

## Risks flagged

1. **Censoring at high MOB:** LAST_VALUE fallback handles this but adds a
   join complexity. The `assert_ecl_origination_pd_populated` test catches NULL
   propagation before it reaches the mart.

2. **Short synthetic history:** Cohorts originated in late 2023 have < 6 months
   of MOB at the as_of_date, making the vintage curve terminal CDR unreliable.
   The absolute delta SICR trigger provides a safety net.

3. **DuckDB portability:** `POWER()` returns DOUBLE in DuckDB. All probability
   calculations are cast to `DECIMAL(10, 8)` explicitly to preserve precision
   on the BigQuery target (per ADR-0001).

4. **mart_finance schema registration:** Requires explicit `+schema: mart_finance`
   in `dbt_project.yml`. Omission causes silent routing to the default schema.
   Added in this phase; verified by inspecting DuckDB after build.
