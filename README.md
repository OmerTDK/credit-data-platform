# credit-data-platform

Multi-product consumer-credit data platform: calibrated synthetic loan book, dimensional + event-sourced dbt warehouse, IFRS 9 ECL, semantic layer, observability

> Status: Phases 0–5 complete. Semantic layer next.

**Phase 5 done:** orchestration + observability + security hardening — Dagster exposes the dbt project as **34 software-defined assets** (28 models + 4 seeds + 3 sources, keyed by schema path) via `@dbt_assets`, materialized by running `dbt build` through `DbtCliResource` (managed subprocess, never a bare shell build). **3 custom `@asset_check` quality gates** with ERROR/WARN severity: `ecl_stage_ecl_strictly_positive` (ERROR — Stage 1 = $1.50 M / Stage 2 = $0.92 M portfolio ECL must be > 0 in every scenario; the ADR-0007 regression, now CI-enforced), `facts_resolve_to_dim_loan` (ERROR — 0 orphan loan_ids across `fct_payment` / `fct_loan_state_event` / `mart_finance_ecl_allowance`), `ecl_allowance_volume_within_band` (WARN — 48,000 rows within band). Gate logic is pure functions with **5 unit + 2 kill tests** (zeroing Stage 1 ECL fires the gate; deleting a `dim_loan` row fires referential integrity). **Elementary** observability: 4 anomaly/schema tests on `fct_payment` + `mart_finance_ecl_summary`, 400 captured test results, a real 7.4 MB `edr report` HTML artifact published from CI. **Security CI layer**: bandit (Python SAST, 0 issues) + pip-audit (0 known CVEs) + gitleaks (secret scan) on every PR. Full Dagster materialization builds **464 dbt nodes** green; full CI green in ~100 s end-to-end — see [ADR-0008](docs/adr/0008-orchestration-dagster-asset-centric.md), [ADR-0009](docs/adr/0009-observability-elementary.md), [ADR-0010](docs/adr/0010-security-ci-layer.md).

**Phase 4 done:** IFRS 9 ECL layer — 11 new dbt models (4 seeds + 5 intermediate views + 2 mart_finance tables), 70 new dbt data tests (2 enforced contracts, 13 custom invariant singular tests), 28 new pytest tests (14 backtest validation + 14 ECL mart integration), 48,000 allowance rows (12,000 loans × 4 scenarios) / 3,584 summary rows — 11,036 Stage 1 / 191 Stage 2 / 773 Stage 3 loans — probability-weighted ECL ~$1.4 M — kill-test verified (assert_ecl_stage3_pd_equals_one: 2,319 violations on mutation) — simplified proxy backtest aggregate coverage ratio 0.67 (acceptance bounds [0.5, 2.0]) — full CI green in ~42 s — see [ADR-0007](docs/adr/0007-ifrs9-ecl-methodology.md).

**Phase 3 done:** risk analytics marts — roll-rate matrix, vintage curves, prepayment speed — 5 new dbt models (3 mart tables + 2 mart-prep intermediate views), 75 new dbt data tests (3 enforced contracts, 10 custom invariant singular tests), 21 new pytest integration tests, 3,633 roll-rate rows / 3,920 vintage-curve rows / 588 prepayment-speed rows — full CI green in ~32 s — see [ADR-0006](docs/adr/0006-risk-marts-methodology.md).

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
                          mart_finance: IFRS 9 ECL allowance + summary (Phase 4)
       |
       v
[ Orchestration ]         Dagster @dbt_assets (DbtCliResource) + 3 asset-check gates (Phase 5)
[ Observability ]         Elementary test-result / volume / schema monitors -> edr report
[ Security CI ]           bandit + pip-audit + gitleaks on every PR
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

### ECL mart layer (Phase 4)

| Model | Grain | Rows | Key design choice |
|-------|-------|------|-------------------|
| `mart_finance.mart_finance_ecl_allowance` | (loan_id, scenario_name) | 48,000 | 3 per-scenario rows + 1 probability-weighted row per loan; enforced contract |
| `mart_finance.mart_finance_ecl_summary` | (as_of_date, product_type, score_band, ifrs9_stage, scenario_name) | 3,584 | Aggregates allowance to portfolio segments |

ECL model: a 5-state Markov chain (recursive CTE in `int_ecl_pd_term_structure`, `default` absorbing) over the count-based roll-rate matrix gives the 12-month PD (12 steps) and a Markov lifetime PD (120 steps); lifetime PD is the worst-case of the Markov lifetime, the vintage-curve terminal CDR, and the 12-month floor. Stage 2 SICR triggers: DPD >= 30 (quantitative backstop) OR relative PD multiple (2.0×) OR absolute PD delta (200 bps) OR watchlist. Stage 3 PD = 1.0 (IFRS 9 §5.5.3). Three scenarios (baseline / adverse / upside) with probability weighting. Discount factor toggleable (off by default). Backtest over 8 quarterly dates (2022-Q1 to 2023-Q4) uses the model's PD term structure (not a flat proxy): aggregate coverage ratio 1.29 (acceptance bounds [0.5, 2.0]) — see ADR-0007.

Two mart-prep intermediates live in `models/intermediate/risk/`:
- `int_risk_roll_rate_observations` — shifted-denominator roll-rate observations; reads `fct_payment`, `fct_loan_state_event`, `dim_loan`
- `int_risk_vintage_cohort_spine` — per-loan-per-MOB view with milestone flags and unscheduled principal; shared by vintage curve and prepayment speed

Ten custom singular tests cover invariants no generic test can express: probabilities sum to 1.0, no negative self-transitions, monotonic cumulative defaults and prepayments, rates in [0,1], CPR formula correctness (1-(1-SMM)^12), non-negative derived counts. Kill-test verified: injecting +1 to `transition_loan_count` fires 1,762 violations; exponent mutant (12→1) fires 454 CPR formula violations.

### Orchestration, observability, and security (Phase 5)

**Dagster.** `src/orchestration/definitions.py` exposes the dbt project as software-defined assets via a single `@dbt_assets` definition over the dbt manifest — 34 assets (28 models + 4 seeds + 3 sources), keyed by schema path. Materialization runs `dbt build` through `DbtCliResource` (a managed subprocess, streamed into Dagster as asset materializations and per-test asset checks). `make dagster-materialize` runs the implicit asset job in-process; `make dagster-dev` opens the browsable asset graph.

**Quality gates.** Three `@asset_check` gates attach to the ECL marts. Their logic lives in pure functions (`src/orchestration/checks.py`) over the built DuckDB, so each is unit- and kill-testable without a Dagster run:

| Gate | Severity | What it catches | Live value |
|------|----------|-----------------|-----------|
| `ecl_stage_ecl_strictly_positive` | ERROR (blocking) | The ADR-0007 regression: a PD-term-structure change zeroing the performing book's allowance. Min per-scenario Stage 1 / Stage 2 portfolio ECL must be > 0. | Stage 1 min $972,372 / Stage 2 min $613,344 |
| `facts_resolve_to_dim_loan` | ERROR (blocking) | Orphan loan_ids in `fct_payment`, `fct_loan_state_event`, `mart_finance_ecl_allowance` not present in `dim_loan`. | 0 orphans |
| `ecl_allowance_volume_within_band` | WARN | ECL allowance row count drifting outside the expected band [20,000, 120,000]. | 48,000 rows |

Kill-test verified: zeroing `total_ecl_amount` for Stage 1 on a copy of the summary mart makes `ecl_stage_ecl_strictly_positive` fail (min_stage1_ecl → 0); deleting one `dim_loan` row makes `facts_resolve_to_dim_loan` fail (orphans > 0).

**Elementary observability.** `fct_payment` (volume anomalies time-bucketed by `report_month` across 35 months + schema changes) and `mart_finance_ecl_summary` (volume anomalies + schema changes) carry Elementary monitors at WARN severity. A full build captures 400 test results into the `elementary` schema; `make elementary-report` produces a real ~7.4 MB `edr report` HTML artifact, uploaded from CI on every PR.

**Security CI.** A separate `security` GitHub Actions job runs on every PR: bandit (Python SAST, **0 issues**), pip-audit (dependency CVEs, **0 known vulnerabilities**), and gitleaks (full-history secret scan). `make security` runs bandit + pip-audit locally.

## Results

| Metric | Value |
|--------|-------|
| Loan book generation | 12,000 loans / 255,131 performance rows in ~2.3 s |
| Staging build | 3 views + 46 data tests in ~0.4 s |
| DWH build (staging + intermediate + DWH) | 9 tables + 7 views + 258 data tests in ~2.4 s |
| Risk mart build (intermediates + 3 mart tables) | 75 data tests in ~0.8 s |
| Full build (all 21 models) | 333 data tests in ~2.1 s |
| Full CI (ruff + sqlfluff + generate + pytest + dbt-parse + scoped builds + Dagster materialize) | ~100 s end-to-end |
| Dagster software-defined assets | 34 (28 dbt models + 4 seeds + 3 sources) via one `@dbt_assets` over the manifest |
| Dagster asset-check gates | 3 custom (2 ERROR-blocking + 1 WARN) + every dbt schema test surfaced as a check |
| Full Dagster materialization | 464 dbt nodes PASS / 0 ERROR (dbt build via DbtCliResource + all gates) |
| Elementary observability | 4 anomaly/schema monitors, 400 captured test results, 7.4 MB `edr report` HTML artifact |
| Security scanners (every PR) | bandit 0 issues + pip-audit 0 known CVEs + gitleaks secret scan |
| Total pytest tests | 401 (391 prior + 10 Phase 5: 5 asset-check unit/kill + 4 Dagster definitions + 1 materialization integration) |
| Custom dbt singular invariant tests | 35 (9 DWH + 10 risk mart + 13 ECL + 3 staging) |
| DWH models with enforced contracts | 9 of 9 |
| Risk mart models with enforced contracts | 3 of 3 |
| ECL mart models with enforced contracts | 2 of 2 |
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
- [ADR-0007](docs/adr/0007-ifrs9-ecl-methodology.md) — IFRS 9 ECL methodology (stationary Markov PD, three SICR triggers, scenario weighting, backtest in Python)
- [ADR-0008](docs/adr/0008-orchestration-dagster-asset-centric.md) — asset-centric orchestration with Dagster + dagster-dbt (asset checks vs Makefile)
- [ADR-0009](docs/adr/0009-observability-elementary.md) — data observability with Elementary (capture gating, anomaly monitors, edr report)
- [ADR-0010](docs/adr/0010-security-ci-layer.md) — security CI layer (bandit + pip-audit + gitleaks)

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

# Install dbt packages (Elementary), then materialize everything through Dagster
# (dbt build via DbtCliResource) and run the asset-check quality gates
uv run dbt deps
make dagster-materialize

# Browse the asset graph + checks in the Dagster UI
make dagster-dev

# Generate the Elementary observability report (artifacts/elementary_report.html)
make elementary-report

# Run the security scanners (bandit + pip-audit)
make security

# Run the full CI suite (ruff + sqlfluff + pytest + dbt builds + Dagster materialize)
make ci
```

## Standards

Engineering conventions in [standards/](standards/) govern all code in this repo.
