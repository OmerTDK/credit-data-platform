# Brief 01 — Multi-Product Credit Data Platform

Repo working title: `credit-data-platform` (finalized in the project's own brainstorm).

## Mission

Build a synthetic-data-backed analytics platform for a fictional multi-product consumer bank carrying mortgages, auto loans, credit cards, and personal loans. The platform demonstrates the full analytics-engineering arc — ingestion → dimensional modeling → credit risk → semantic layer → observability and cost — on a loan book that is realistic, reproducible, and fully shareable.

This is the depth anchor of the portfolio: one repo, structured internally as a monorepo, whose sub-components (synthetic generator, dbt project, risk layer, semantic layer, observability) share one data foundation, one CI pipeline, and one top-level architecture diagram.

## Staff signal

**Axis A — batch architecture & modeling (depth).** This project clears the staff bar on all four thesis criteria:

1. **Architectural judgment you can defend** — named patterns (event sourcing, SCD2, accumulating snapshot), every major decision documented as an ADR with the tradeoff, explicit grain per model.
2. **Reliability engineering** — dbt contracts on mart models, custom tests (balance reconciliation, valid state transitions), observability with freshness and volume anomaly detection, documented SLAs.
3. **Self-serve enablement** — a semantic layer where metrics are defined once and shared by BI tools and an API; generated docs published.
4. **Impact quantified** — runtime, cost per model, test counts, warehouse spend in the README results section. Real numbers, not adjectives.

Multi-product consumer credit is deliberately a richer modeling problem than any single product, and it signals broad understanding of lending rather than one niche.

## Scope

**In:**

- Synthetic data generator (Python) for all four products, calibrated against public loan-performance data, reproducible from a fixed seed.
- Ingestion/landing of raw data into the warehouse (ELT).
- dbt transformation spine: staging → intermediate → marts (dimensional, event-sourced loan state, risk/analytics).
- Risk marts: roll-rate matrices, vintage curves, CPR/SMM prepayment curves.
- IFRS 9 ECL layer: parameterized PD/LGD/EAD, staging (1/2/3), scenario-driven, backtested.
- Semantic/metrics layer with 1–2 dashboards or a metrics API.
- Observability (test results, freshness, volume anomalies), warehouse cost attribution, documented SLAs.
- Orchestration, CI/CD, ADRs, generated docs.

**Out:**

- Real-time/streaming workloads (separate portfolio project).
- Fraud feature engineering and online serving (separate portfolio project — brief 03).
- LLM/natural-language interface (separate portfolio project — brief 04; it consumes this platform's semantic layer).
- Trained ML credit-scoring models — PD/LGD/EAD are parameterized and scenario-driven, not fitted.
- Any real customer or production data. Everything is synthetic or public.

## Architecture

Eight layers, top to bottom:

1. **Synthetic data generator (Python).** Produces a realistic, reproducible loan book from a fixed seed: origination cohorts, borrower attributes, credit scores, and monthly performance (payments, delinquency transitions, prepayment, default, recovery) across all four products. Writes to a landing zone (parquet → object storage, or local files).
2. **Ingestion/landing (ELT).** Load raw into the warehouse. `dlt` optional for the ingestion-tooling signal.
3. **Transformation (dbt) — the spine.**
   - *Staging* — cleaning + typing, 1:1 with source.
   - *Intermediate* — business logic.
   - *Marts:*
     - Dimensional: `dim_borrower` (SCD2), `dim_loan`, `dim_product`, `dim_date`; `fct_loan_origination`, `fct_payment`; accumulating-snapshot `fct_loan_lifecycle` (one row per loan, milestone timestamps fill in over time).
     - Loan state as **event sourcing** — an immutable stream of state-transition events; current state is *derived*, not overwritten.
     - Risk/analytics marts: **roll-rate matrices** (delinquency transition probabilities), **vintage curves** (cumulative default/prepayment by origination cohort × months-on-book), **CPR/SMM** prepayment curves.
4. **Credit-risk layer — IFRS 9 ECL.** Parameterized PD/LGD/EAD, staged (1/2/3), scenario-driven, fully reproducible, backtested. dbt + Python.
5. **Semantic/metrics layer.** Define metrics once (dbt Semantic Layer / MetricFlow, or Cube) so BI tools and an API share one definition. Removes metric drift.
6. **Observability + cost.** Elementary for dbt test results plus freshness/volume anomaly detection; a warehouse cost-attribution view (cost per model/mart); documented SLAs.
7. **Orchestration.** Dagster (shows maturity) or dbt Cloud / GitHub Actions cron.
8. **CI/CD.** SQLFluff lint, `dbt build` + tests on PR, pre-commit hooks, generated docs site, GitHub Actions.

**Data strategy (hybrid — synthetic, calibrated against public data).** Pure synthetic gives scenario control (inject a default wave, a prepayment spike) and full shareability; public datasets give realism. The hybrid takes both: calibrate the generator's distributions against real loan-performance data, then generate at any volume. The calibration step is itself a senior signal. Public calibration sources:

- **Fannie Mae / Freddie Mac single-family loan-performance data** — real delinquency + prepayment histories; ideal for roll rates and CPR/SMM.
- **Lending Club historical loan data** (mirrored on Kaggle) — consumer-loan attributes + outcomes.
- **PaySim** (Kaggle) — the payments/fraud transaction shape.

Availability and links shift — verify current sources at build time.

**ADR seeds (the defensible-judgment layer — document each as an ADR):**

- Event-sourced loan state vs. a mutable status column → auditability + point-in-time correctness ("what did this loan look like on any date").
- SCD2 borrower dimension → answer "attributes *at origination*" vs. current.
- Accumulating-snapshot fact → natural fit for loan-lifecycle milestones.
- Synthetic-but-calibrated data → realism + shareability + scenario control.
- Explicit grain documented per model.
- Incremental models + partitioning/clustering for cost control.
- Tests beyond `not_null`/`unique` → `accepted_values`, `relationships`, custom tests (balances reconcile, no negative balances, valid state transitions), plus dbt contracts on mart models.
- Metrics live in the semantic layer, never hardcoded in BI.

## Build phases

One session + one PR per phase. Each phase ends with an ADR, tests, and a README update.

- **Phase 0** — repo scaffold, CI, standards wired in, DuckDB local + BigQuery target, profiles.
- **Phase 1 (keystone)** — synthetic generator: one product end-to-end first, then all four; reproducible seed; calibrate distributions against the public loan-performance data.
- **Phase 2** — staging + core dimensional marts + lifecycle fact.
- **Phase 3** — risk marts (roll rates, vintage curves, CPR/SMM).
- **Phase 4** — IFRS 9 ECL.
- **Phase 5** — semantic layer + 1–2 dashboards / a metrics API.
- **Phase 6** — observability + cost attribution + SLAs.

## Stack

- **Warehouse:** DuckDB for local dev + **BigQuery** as the real target. Supporting both also demonstrates portability — a senior signal.
- **Transform:** dbt.
- **Languages:** Python (generator, ECL, checks), SQL (models).
- **Semantic layer:** dbt Semantic Layer / MetricFlow, or Cube (decided in an ADR).
- **BI:** Metabase and/or Qlik on the semantic layer.
- **Observability:** Elementary.
- **Orchestration:** Dagster or GitHub Actions cron (decided in an ADR).
- **CI/CD:** GitHub Actions, SQLFluff, pre-commit, generated dbt docs site.

## Deployed means

Scheduled dbt runs against BigQuery via GitHub Actions, plus a published dbt docs site. A reviewer can see the pipeline running on a schedule and browse the generated documentation without cloning anything.

## Dependencies

None — this is the first project. The synthetic data generator is the keystone: three of the four other portfolio projects consume this platform's output — the OSS dbt package extracts its risk marts, the LLM analyst sits on its semantic layer, and the fraud feature store uses its transaction-shaped data (with a standalone PaySim-shaped fallback) — so this repo starts first and Phase 1 is the program's critical path.

## Definition of done

- [ ] README that tells the **system story**, with an architecture diagram.
- [ ] **ADRs** for each major design decision (the tradeoff, not just the choice).
- [ ] **Full CI green** — lint + tests on every PR.
- [ ] Meaningful **tests / data contracts** (not just `not_null`/`unique`).
- [ ] **Observability** where applicable (test results, freshness, anomalies).
- [ ] A **results section** with quantified outcomes (runtime, cost, test count, savings).
- [ ] **Generated docs** published.
- [ ] A short writeup of the **single hardest design decision**.
- [ ] Conforms to **Omer's coding standards** (§6).
- [ ] **Public** repo with a clean history once polished.
