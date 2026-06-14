# ADR-0006: Risk marts methodology — roll rates, vintage curves, prepayment speed

**Date:** 2026-06-14
**Status:** Accepted

## Context

Phase 3 builds three analytical mart models on top of the DWH layer (ADR-0005) to answer the
credit-risk management questions the platform exists to serve:

1. **Roll rates** — how quickly do delinquent loans improve or worsen? What fraction of loans
   in each delinquency state remain there, cure, or roll forward each month?
2. **Vintage curves** — do 2022 originations perform worse than 2023 originations? What is the
   cumulative default rate at 12/24/36 months on book, by product and score band?
3. **Prepayment speed** — how fast is the book paying down voluntarily? What is the CPR by
   cohort, enabling duration and convexity analysis?

Five structural choices are forced before the first model is written:

1. What is the correct denominator for roll-rate transition probabilities?
2. How should vintage curves count loans that exit `fct_payment` after default or payoff?
3. Which prepayment rate convention (PSA SMM/CPR, absolute, balance-weighted)?
4. How should the intermediate layer relate to the DWH — shared spine or per-mart?
5. How should the mart contract protect the quantitative invariants?

## Decisions

### 1. Roll-rate denominator: loans in each bucket at the START of each observation period

The roll-rate matrix must produce transition probabilities that sum to 1.0 across all
destination buckets for each (from_bucket, observation_period) partition. This requires a
correct denominator.

**Incorrect approach (rejected):** Count loans where `fct_payment.delinquency_bucket = X` at
`report_month = M` (the current month's end-of-period state). This counts loans that ENDED
in bucket X, but the transition events in `fct_loan_state_event` carry `from_delinquency_bucket`
= the state at the BEGINNING of the period. Joining them produces mismatched populations —
the denominator and numerator refer to different time points — which causes self-transition
counts to go negative (more loans transitioned out than were counted as at-risk).

**Accepted approach:** Shift `fct_payment.delinquency_bucket` forward by one period:
`loan_period_starts` contains the bucket at the END of month M−1 (= start of month M),
paired with `observation_period = month M`. This ensures:
- Denominator = loans in bucket X at the START of observation period M.
- Numerator (non-self transitions) = loans that changed from bucket X to another bucket
  during period M, sourced from `fct_loan_state_event.from_delinquency_bucket = X` at
  `report_month = M`.
- Self-transition residual = denominator minus all non-self transitions = exact remainder.

The `assert_mart_risk_roll_rate_probabilities_sum_to_one` custom test verifies this invariant
on every build. Kill test: adding +1 to `transition_loan_count` for every row produces 1,762
violations. The test fires.

**Trade-off:** Only loans with a subsequent `fct_payment` row are included in the denominator
(confirmed via the inner join to `subsequent_payment`). Loans that default or pay off in period
M−1 and therefore have no month-M row are excluded from the denominator. This is the correct
actuarial choice: a loan that terminated before the observation period starts cannot be at risk
of transitioning during it.

### 2. Vintage curves: cohort-level MOB spine instead of payment spine

A payment-spine approach (counting `has_defaulted_by_mob = TRUE` rows from
`int_risk_vintage_cohort_spine`) causes cumulative default counts to decrease non-monotonically:
once a loan defaults and exits `fct_payment` (it has no more payment rows), it disappears from
the SUM, so the cumulative count drops. For a 24-cohort × 4-product × 5-score-band book, this
produced 332 monotonicity violations.

**Accepted approach:** Compute cumulative counts from an explicit (loan × MOB range) cross-join
anchored to `fct_loan_lifecycle` milestone months. For each loan, `default_mob` and
`prepayment_mob` are computed as month-offsets from `origination_month`. A loan is flagged
`has_defaulted_by_mob` for all MOBs ≥ `default_mob`, regardless of whether the loan still has
a `fct_payment` row at that MOB. This produces:
- `cumulative_default_count` that is provably non-decreasing across MOBs for each cohort.
- `cumulative_prepayment_count` over the surviving-non-defaulted pool (a defaulted borrower
  cannot prepay — this is the ABS/industry convention and removes the double-counting ambiguity).
- A `mob_numbers` CTE (range 1–99) cross-joined to cohort sizes so no inline subqueries violate
  the clean-sql standard.

**Credit card `cohort_principal`:** Credit cards have `principal_amount = NULL` and
`credit_limit_amount > 0`. The `originations` CTE uses
`COALESCE(principal_amount, 0) + COALESCE(credit_limit_amount, 0)` so credit card cohorts
carry the credit limit as `cohort_principal` rather than NULL.

**Trade-off:** The explicit MOB spine cross-joins every loan in the cohort to every MOB from 1
to max_mob. For 12,000 loans × 99 max MOBs, this is up to 1.19 million rows in the intermediate
fan-out before aggregation. At the synthetic book's scale (255K payment rows), this is
acceptable. For a production book at 1M+ loans, the intermediate would require incremental
materialization or partitioning.

**Custom test verification:** `assert_mart_risk_vintage_cumulative_default_monotonic` uses a
LAG window to detect any row where `cumulative_default_count < prev_cumulative_default_count`.
Zero violations with the accepted implementation.

### 3. Prepayment speed: SMM/CPR balance-weighted, amortizing-only

**SMM (Single Monthly Mortality):**
`SMM = prepaid_balance / performing_pool_balance`

where:
- `performing_pool_balance` = sum of `beginning_balance_amount` for active, non-prepaying loans
  entering the month (the pool at risk of prepaying).
- `prepaid_balance` = `unscheduled_principal` = `GREATEST(actual_payment - scheduled_payment, 0)
  × is_prepayment`. This correctly handles partial prepayments: a borrower who pays extra but
  does not close the loan contributes only the unscheduled portion to the numerator, not the
  full balance.

**CPR:** `1 - (1 - SMM)^12` per PSA convention. The exponent 12 is extracted to a `constants`
CTE as `months_per_year = 12` per clean-sql.md rule (no magic numbers). POWER() is standard
SQL, portable across DuckDB and BigQuery.

**Credit cards excluded:** `is_amortizing = FALSE` on credit cards in `dim_loan`, propagated
through `int_risk_vintage_cohort_spine`. The `WHERE is_amortizing` filter in
`mart_risk_prepayment_speed` removes credit cards at the intermediate level. The
`accepted_values` test on `product_type` in the mart YAML (personal_loan, auto_loan, mortgage)
is self-documenting — credit_card never appears, making the exclusion verifiable.

**NULL semantics:** `smm_rate` and `cpr_rate` are NULL when `performing_pool_balance = 0`.
The `assert_mart_risk_smm_in_unit_interval` test is limited to non-NULL rows.

### 4. Intermediate spine used by prepayment speed only

`int_risk_vintage_cohort_spine` is a per-loan-per-MOB view that carries payment attributes
(`beginning_balance_amount`, `unscheduled_principal`, `is_prepayment`, `loan_status`). It is
used exclusively by `mart_risk_prepayment_speed`, where we want the payment rows as-observed
(including exit: a prepaid loan's `is_prepayment = TRUE` in its final month is precisely what
the SMM numerator needs).

`mart_risk_vintage_curve` does NOT use this spine — it reads `fct_loan_origination` and
`fct_loan_lifecycle` directly for its cumulative-count computation via an explicit
(loan × MOB range) cross-join (see §2 above). Using the payment spine for the vintage curve
would drop exited loans from cumulative counts.

**Why not one CTE inside each mart:** The spine joins three DWH tables (`fct_loan_origination`,
`dim_loan`, `fct_payment`) and computes `unscheduled_principal`. Embedding this in the mart CTE
would exceed the 80-line CTE limit from `engineering-principles.md` §2. Extracting it to the
intermediate layer keeps the mart readable without adding a new abstraction level.

### 5. Contract enforcement on all three mart models

All three mart models have `contract: enforced: true`. Contracts require exact column names and
data types to match. Key lessons from the build:

- `count(distinct ...)` returns BIGINT in DuckDB. Explicit `CAST(... AS INTEGER)` is required in
  the mart SELECT clause to satisfy an `integer` contract column.
- `date_trunc('quarter', date_col)` returns TIMESTAMP in DuckDB when operating on a DATE column.
  Explicit `CAST(date_trunc(...) AS DATE)` is required in intermediates that feed contracted marts.
- `unnest(range(1, N))` returns BIGINT. Explicit `CAST(... AS INTEGER)` required for integer
  contract columns.

The `score_band` accepted_values test uses `subprime` (the actual generator value), not
`sub_prime` (the design document value). Always verify against the data rather than quoting
design documents.

### 6. OSS extraction fit

The three mart models and two intermediates are designed for extraction into the OSS
`dbt-credit-risk` package (brief 02 Phase 3 deliverable). The extraction path:

- `int_risk_roll_rate_observations.sql` and `int_risk_vintage_cohort_spine.sql` become source
  adapters: `ref()` calls replaced with `source()` pointing at the consumer's DWH tables.
- `mart_risk_roll_rate_matrix` and `mart_risk_prepayment_speed` reference only the two
  intermediates and are portable as-is.
- `mart_risk_vintage_curve` references `fct_loan_origination` and `fct_loan_lifecycle` from the
  DWH directly (via its own originations CTE). Extracting it to the OSS package requires two
  additional source adapters for those two DWH tables.
- Custom singular tests become the package's integration test suite.
- `roll_rate_period_months` and `vintage_cohort_granularity` dbt vars map directly to documented
  macro arguments.
- Accepted_values for bucket labels and product types become the package's documented input
  contract; callers with different bucket names pass a column-mapping argument.

Estimated extraction effort: four source-config files (two intermediates + two vintage-curve DWH
refs), one `packages.yml` entry, zero mart SQL changes beyond the source adapter swap.

## Alternatives considered

### Mutable column denominator for roll rates

Use `fct_payment.delinquency_bucket` (current-month state) as both denominator and "from"
label. Rejected: produces mismatched denominator/numerator time points and negative
self-transition counts on the real data.

### Event stream only for denominator

Source the denominator exclusively from `fct_loan_state_event.from_delinquency_bucket` (only
loans that actually transitioned). Rejected: this would exclude the large majority of loans
that stayed in their bucket (the self-transitions) from the denominator, making all non-self
probabilities sum to 1.0 trivially — a meaningless result.

### Payment-spine vintage curves

Rejected (§2 above): produces 332 monotonicity violations on the synthetic data. The explicit
MOB-range spine is required for correct cumulative counts.

### Hazard rate instead of cumulative default rate

Alternative convention: incremental (period-specific) default rate per MOB rather than
cumulative. Not implemented in this phase because:
1. Cumulative is the industry standard for vintage curve comparisons (ABS/Fannie Mae).
2. `loans_at_risk_count` is exposed in the mart, enabling hazard rate computation by consumers.
3. IFRS 9 (Phase 4) will use cumulative PD curves as inputs.

### CPR as annualized from monthly occurrence count

Alternative: CPR = count of loans that prepaid in month / total loans at risk. Rejected: count-
based CPR is distorted by loan size distribution and is not the industry convention for pool
analysis. Balance-weighted SMM/CPR per PSA is the mortgage-backed security standard and is more
meaningful when loans have heterogeneous principal amounts. Both count-based and balance-based
columns are exposed in the mart for cross-verification.

## Consequences

- `mart_risk_vintage_curve` uses a cross-join of (loans × MOB range), which fans out to
  ~O(loans × max_MOB) rows before aggregation. At 12,000 loans × 35 MOBs = ~420K rows in the
  intermediate, aggregated to 3,920 mart rows. This is fast at synthetic scale but requires
  partitioning at 1M+ loan production scale.
- `int_risk_vintage_cohort_spine` feeds `mart_risk_prepayment_speed` only. Changes to the
  spine's grain or column names require updates to the prepayment speed mart.
  The spine's grain and contract are documented in `_intermediate_risk__models.yml`.
- The OSS extraction is straightforward (see §6) because the three marts only ref the two
  intermediates. No mart references DWH directly.

## Grain summary

| Model | Grain |
|-------|-------|
| `int_risk_roll_rate_observations` | One row per (product_type, score_band, observation_period, from_bucket, to_bucket) |
| `int_risk_vintage_cohort_spine` | One row per (loan_id, origination_cohort_quarter, months_on_book) |
| `mart_risk_roll_rate_matrix` | One row per (product_type, score_band, observation_period, from_bucket, to_bucket) — same as intermediate |
| `mart_risk_vintage_curve` | One row per (origination_cohort_quarter, product_type, score_band, months_on_book) |
| `mart_risk_prepayment_speed` | One row per (origination_cohort_quarter, product_type, months_on_book) — amortizing only |

## Hardest design decision

**The roll-rate denominator** is the hardest and most consequential choice. Intuitively, "loans
in bucket X in observation period M" sounds obvious — but the DWH stores the state at the END
of each period (fct_payment.delinquency_bucket = state after this month's payments). The
transition events store the state at the BEGINNING of each period (from_delinquency_bucket =
state before this month's transition). Confusing these two produces transition probabilities
that violate the probability axiom (they don't sum to 1). The correct fix — shifting one period
forward to align denominator time point with event time point — is not obvious from the schema
alone. It required running the data and observing negative self-transition counts to diagnose.

The `assert_mart_risk_roll_rate_probabilities_sum_to_one` test exists to prevent this class of
error from silently entering the mart in any future refactor.
