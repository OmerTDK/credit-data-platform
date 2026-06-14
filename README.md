# credit-data-platform

Multi-product consumer-credit data platform: calibrated synthetic loan book, dimensional + event-sourced dbt warehouse, IFRS 9 ECL, semantic layer, observability

> Status: under construction — not yet at definition-of-done.

**Phase 3 done:** risk analytics marts — roll-rate matrix, vintage curves, prepayment speed — 5 new dbt models (3 mart tables + 2 mart-prep intermediate views), 73 new dbt data tests (3 enforced contracts, 6 custom invariant singular tests), 17 new pytest integration tests, 3,633 roll-rate rows / 3,920 vintage-curve rows / 588 prepayment-speed rows — full CI green in ~32 s — see [ADR-0006](docs/adr/0006-risk-marts-methodology.md).

**Phase 2b done:** dimensional + event-sourced DWH layer — 9 models across `dwh` schema (3 conformed dims, 1 SCD2 borrower dim, 1 event-sourced current-state dim, 2 facts, 1 accumulating-snapshot lifecycle fact, 1 immutable state-event stream), dbt contracts on all 9 models, 191 DWH data tests (relationships including borrower_key FK on all 5 fact/dim models, accepted_values with not_null, 9 custom invariant tests), 17 new pytest fixtures asserting row counts and data invariants, full CI green in ~32 s end-to-end — see [ADR-0005](docs/adr/0005-dimensional-layer-and-event-sourced-loan-state.md).

**Phase 2a done:** dbt sources + staging layer over the parquet landing zone — 3 staging views (`stg.loanbook__*`) read the landing parquet in place via dbt-duckdb `external_location`, per-layer schema mapping (`stg`/`int`/`dwh`/`mart_risk`/`mart_finance`), 45 dbt data tests green in CI against the generated four-product book — see [ADR-0003](docs/adr/0003-external-parquet-sources-and-schema-mapping.md). Phase 1 done: seeded synthetic loan-book generator (`loanbook`, all four products — personal loans, auto loans, mortgages, credit cards) — delinquency state machine with validated transitions, per-product calibration anchored to published statistics ([sources](docs/calibration-sources.md)), byte-identical parquet from a fixed seed (12,000 accounts / 255,131 monthly rows / 9.3 MB in ~2.3 s via `make generate`) — see [ADR-0002](docs/adr/0002-synthetic-generator-architecture.md) and [ADR-0004](docs/adr/0004-multi-product-extension.md). Phase 0: dbt skeleton, DuckDB dev target, CI gates (`dbt parse`, SQLFluff); BigQuery prod target pending — see [ADR-0001](docs/adr/0001-dual-target-warehouse.md).

## Why this exists

A consumer lender running four credit products (mortgages, auto loans, personal loans, credit cards) has data that needs to answer very different questions depending on who is asking:

- **Risk:** what is the current delinquency roll rate? How do vintage cohorts of 2022 originations compare to 2023?
- **Finance:** what is total outstanding principal? Where is the book relative to ECL reserves?
- **Operations:** which borrowers are approaching 90 DPD? Which loans have been in recovery for more than 6 months?

Each question requires a different model shape, but they all need a single consistent view of the loan book. This platform demonstrates how to build that consistency: a shared dimensional foundation (conformed dims, event-sourced state), composed into domain-specific marts, with observable SLAs and a semantic layer that stops metric definitions from drifting between teams.

The loan book is fully synthetic and reproducible from a fixed seed — shareable without privacy constraints, yet statistically realistic: delinquency transitions, prepayment rates, and loss curves are anchored to published consumer-lending data.

## Architecture

```
Landing zone (parquet)
       |
       v
[ Staging (stg) ]         3 views, 1:1 with source, typed + renamed
       |
       v
[ Intermediate (int) ]    6 views, business logic, SCD2 prep + mart-prep risk
       |
       v
[ DWH (dwh) ]             9 tables: 4 dims + 1 SCD2 + 1 event-stream + 3 facts
       |
       v
[ Marts ]                 mart_risk: roll-rate matrix, vintage curves, prepayment speed
```

### DWH layer (Phase 2b)

| Model | Pattern | Grain | Rows |
|-------|---------|-------|------|
| `dim_date` | Conformed calendar dim | 1 per calendar day | 3,653 |
| `dim_product` | Conformed product dim | 1 per product type | 4 |
| `dim_loan` | Loan static dim | 1 per originated loan | 12,000 |
| `dim_borrower` | SCD2 (time-varying delinquency bucket) | 1 per (borrower, version) | 19,257 |
| `dim_loan_current_state` | Derived current state from event stream | 1 per loan | 12,000 |
| `fct_loan_origination` | Origination fact | 1 per originated loan | 12,000 |
| `fct_payment` | Monthly payment fact | 1 per (loan, month on book) | 255,131 |
| `fct_loan_state_event` | Immutable event stream | 1 per state-change event | 21,320 |
| `fct_loan_lifecycle` | Accumulating snapshot | 1 per loan (milestones fill in) | 12,000 |

**Event sourcing:** `fct_loan_state_event` records every state transition (delinquency bucket change, lifecycle status change) as an immutable event. `dim_loan_current_state` is derived deterministically from this stream — current state is never stored directly, always computed. A custom test verifies that the event-stream derivation matches an independent direct computation from the performance table.

**SCD2:** `dim_borrower` tracks `current_delinquency_bucket` (worst delinquency across all the borrower's loans each month) as the time-varying attribute. Version boundaries open whenever this bucket changes. 7,257 extra version rows across 2,323 borrowers who entered delinquency at least once. See [ADR-0005](docs/adr/0005-dimensional-layer-and-event-sourced-loan-state.md) for why this attribute was chosen over a tautological one-version SCD2.

**Accumulating snapshot:** `fct_loan_lifecycle` holds one row per loan with milestone date columns (origination, first payment, first 30/60/90 DPD, default, payoff, recovery). Milestone-to-milestone durations are single-column arithmetic — no self-joins required.

### Risk mart layer (Phase 3)

| Model | Grain | Rows | Key design choice |
|-------|-------|------|-------------------|
| `mart_risk.mart_risk_roll_rate_matrix` | (product, score_band, period, from_bucket, to_bucket) | 3,633 | Denominator = loans at START of period; self-transition is residual arithmetic |
| `mart_risk.mart_risk_vintage_curve` | (cohort_quarter, product, score_band, months_on_book) | 3,920 | Explicit cohort × MOB cross-join — loans in terminal state not dropped |
| `mart_risk.mart_risk_prepayment_speed` | (cohort_quarter, product, months_on_book) | 588 | PSA SMM/CPR, amortizing only; credit cards excluded via `is_amortizing` |

Two mart-prep intermediates live in `models/intermediate/risk/`:
- `int_risk_roll_rate_observations` — shifted-denominator roll-rate observations; reads `fct_payment`, `fct_loan_state_event`, `dim_loan`
- `int_risk_vintage_cohort_spine` — per-loan-per-MOB view with milestone flags and unscheduled principal; shared by vintage curve and prepayment speed

Six custom singular tests cover invariants no generic test can express: probabilities sum to 1.0, no negative self-transitions, monotonic cumulative defaults, rates in [0,1]. Kill-test verified: injecting +1 to `transition_loan_count` in the roll-rate mart fires 1,762 violations.

## Results

| Metric | Value |
|--------|-------|
| Loan book generation | 12,000 loans / 255,131 performance rows in ~2.3 s |
| Staging build | 3 views + 46 data tests in ~0.4 s |
| DWH build (staging + intermediate + DWH) | 9 tables + 7 views + 258 data tests in ~2.4 s |
| Risk mart build (intermediates + 3 mart tables) | 73 data tests in ~0.8 s |
| Full build (all 21 models) | 331 data tests in ~2.1 s |
| Full CI (ruff + sqlfluff + generate + pytest + dbt-parse + dbt-build) | ~32 s end-to-end |
| Total dbt data tests | 331 (46 staging + 30 intermediate + 191 DWH + 64 mart-schema + 6 mart-custom + 4 intermediate-custom) |
| Total pytest tests | 359 (325 generator + 3 staging integration + 14 DWH integration + 17 risk-mart integration) |
| Custom dbt singular invariant tests | 15 (9 DWH + 6 risk mart: roll-rate probabilities sum-to-one, no negative self-transition, monotonic vintage defaults, prepayment rate in [0,1], SMM in [0,1], no null from_bucket) |
| DWH models with enforced contracts | 9 of 9 |
| Risk mart models with enforced contracts | 3 of 3 |
| roll_rate_matrix rows | 3,633 (product × score_band × period × from_bucket × to_bucket transitions) |
| vintage_curve rows | 3,920 (cohort × product × score_band × MOB — all MOBs carried even after loan exits payment) |
| prepayment_speed rows | 588 (amortizing products only; credit cards excluded via is_amortizing filter) |
| SCD2 versions (dim_borrower) | 19,257 across 12,000 borrowers (max 12 versions per borrower) |
| Event stream rows | 21,320 (12,000 origination + 7,257 delinquency transitions + 2,063 lifecycle transitions) |

## Design decisions

See [docs/adr/](docs/adr/) — each major decision documented with its trade-offs.

- [ADR-0001](docs/adr/0001-dual-target-warehouse.md) — DuckDB dev + BigQuery prod, deferred prod target
- [ADR-0002](docs/adr/0002-synthetic-generator-architecture.md) — state-machine generator with calibrated hazard rates
- [ADR-0003](docs/adr/0003-external-parquet-sources-and-schema-mapping.md) — external parquet sources + schema mapping
- [ADR-0004](docs/adr/0004-multi-product-extension.md) — multi-product extension (auto, mortgage, credit card)
- [ADR-0005](docs/adr/0005-dimensional-layer-and-event-sourced-loan-state.md) — dimensional layer and event-sourced loan state
- [ADR-0006](docs/adr/0006-risk-marts-methodology.md) — risk marts methodology (roll-rate denominator, vintage MOB spine, SMM/CPR)

## Quickstart

```bash
git clone https://github.com/OmerTDK/credit-data-platform
cd credit-data-platform
uv sync

# Generate the synthetic loan book (fixed seed, reproducible)
make generate

# Build and test the full DWH (staging + intermediate + DWH)
make dbt-build-dwh

# Build risk marts on top of the DWH
uv run dbt build --select "int_risk_roll_rate_observations int_risk_vintage_cohort_spine mart_risk_roll_rate_matrix mart_risk_vintage_curve mart_risk_prepayment_speed" --profiles-dir .

# Run the full CI suite (ruff + sqlfluff + pytest + dbt build)
make ci
```

## Standards

Engineering conventions in [standards/](standards/) govern all code in this repo.
