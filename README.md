[![CI](https://github.com/OmerTDK/credit-data-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/OmerTDK/credit-data-platform/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](pyproject.toml)
[![dbt](https://img.shields.io/badge/dbt-1.11%2B-orange.svg)](dbt_project.yml)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.2%2B-yellow.svg)](pyproject.toml)

# credit-data-platform

A production-grade consumer-credit data platform: calibrated synthetic loan book, dimensional + event-sourced dbt warehouse, IFRS 9 ECL, governed semantic layer, and full-stack observability — all running locally on DuckDB with a BigQuery prod target.

## The problem

Consumer lending data needs to answer fundamentally different questions for different teams — risk wants roll rates and vintage curves, finance needs ECL reserves, operations needs current delinquency status — but every team needs to read from the same consistent view of the loan book.

Most analytics stacks solve this by duplicating models. This platform solves it the right way: a shared dimensional foundation built on an immutable event stream, composed into domain-specific marts, with a MetricFlow semantic layer that makes metric definitions a single source of truth across every consumer.

The loan book is fully synthetic and reproducible from a fixed seed — statistically realistic delinquency transitions, prepayment speeds, and loss curves anchored to published consumer-lending data, with zero privacy constraints.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Generator (Python)                                                 │
│  12K loans · 4 products · 255K performance rows · fixed seed        │
└────────────────────────┬────────────────────────────────────────────┘
                         │ Parquet / Iceberg
              ┌──────────┴──────────────────────────┐
              │  Landing Zone                        │
              │  Parquet (dbt-duckdb external)       │
              │  Iceberg (PyIceberg + SQLite catalog) │
              └──────────┬──────────────────────────┘
                         │
              ┌──────────▼──────────────────────────┐
              │  Staging  (stg)                      │
              │  3 views · typed · 46 data tests     │
              └──────────┬──────────────────────────┘
                         │
              ┌──────────▼──────────────────────────┐
              │  Intermediate  (int)                 │
              │  6 core views + 7 ECL/risk views     │
              │  SCD2 prep · roll-rate obs           │
              └──────────┬──────────────────────────┘
                         │
              ┌──────────▼──────────────────────────┐
              │  DWH  (dwh)                          │
              │  9 tables · dbt contracts enforced   │
              │  4 conformed dims · SCD2 borrower    │
              │  immutable event stream · 3 facts    │
              └──────────┬──────────────────────────┘
                         │
           ┌─────────────┴─────────────┐
           │                           │
┌──────────▼───────────┐   ┌──────────▼───────────┐
│  mart_risk            │   │  mart_finance         │
│  Roll-rate matrix     │   │  IFRS 9 ECL allowance │
│  Vintage curves       │   │  48K rows · 4 scenarios│
│  Prepayment speed     │   │  Markov PD term struct │
└──────────┬───────────┘   └──────────┬────────────┘
           └─────────────┬─────────────┘
                         │
     ┌───────────────────┼───────────────────────────┐
     │                   │                           │
┌────▼──────┐   ┌────────▼────────┐   ┌─────────────▼────────┐
│ Dagster   │   │ Elementary      │   │ MetricFlow + Evidence │
│ 65 assets │   │ Observability   │   │ 7 governed metrics    │
│ 3 quality │   │ 400 test results│   │ 4-page static BI site │
│ gates     │   │ 7.4 MB edr rpt  │   │ query-gated in CI     │
└───────────┘   └─────────────────┘   └──────────────────────┘
                         │
              ┌──────────▼──────────────────────────┐
              │  Security CI                         │
              │  bandit · pip-audit · gitleaks       │
              │  0 SAST issues · 0 known CVEs        │
              └──────────┬──────────────────────────┘
                         │
              ┌──────────▼──────────────────────────┐
              │  BigQuery (prod)                     │
              │  Terraform IaC · 6 datasets          │
              │  Scheduled via GitHub Actions        │
              └─────────────────────────────────────┘
```

## Key features

- **Calibrated synthetic loan book** — state-machine generator produces 4 credit products (personal loans, auto loans, mortgages, credit cards) with hazard rates anchored to published statistics. Byte-identical output from a fixed seed; runs in ~2.3 s.
- **Event-sourced DWH** — loan state transitions are recorded as an immutable event stream. Current state is derived deterministically; point-in-time correctness is structural, not procedural. A custom dbt test verifies the derivation against an independent computation.
- **SCD2 borrower dimension** — tracks worst delinquency across all loans per borrower over time. 19,257 version rows across 12,000 borrowers, computable only because the event stream makes version boundaries explicit.
- **IFRS 9 ECL** — full three-stage classification, 5-state Markov PD term structure (recursive CTE), three probability-weighted scenarios, backtested over 8 quarterly dates. Coverage ratio 1.29 (bounds [0.5, 2.0]).
- **Risk analytics marts** — roll-rate matrix with shifted-denominator semantics, vintage loss curves (explicit cohort × MOB cross-join with terminal-state loans preserved), PSA SMM/CPR prepayment speed for amortizing products.
- **35 custom dbt invariant tests** — probabilities sum to 1.0, CPR formula verification (1−(1−SMM)^12), monotonic cumulative defaults, SCD2 chain integrity, ECL amounts in [0, EAD]. Kill-tested with data mutations.
- **Dagster asset-centric orchestration** — 65 software-defined assets via a single `@dbt_assets` over the manifest. Three `@asset_check` quality gates (2 ERROR-blocking, 1 WARN) with pure-function logic independently unit- and kill-tested.
- **Elementary observability** — volume anomaly + schema monitors on key fact tables, 400 captured test results, 7.4 MB HTML report published from every CI run.
- **MetricFlow semantic layer** — 7 governed metrics defined once over the DWH/marts, queryable with the open-source `mf` CLI against DuckDB. All metric values pinned in CI; a definition change that moves a number fails the build.
- **Evidence BI-as-code dashboard** — 4-page static site (portfolio overview, vintage curves, risk-cohort drill-down, FinOps cost view). SQL source queries gated in CI — no Node/network required.
- **Apache Iceberg landing zone** — PyIceberg with a local SQLite catalog. Time travel and schema evolution exercised end-to-end in CI via DuckDB `iceberg_scan()`.
- **BigQuery prod target** — `profiles.yml` prod output, `dbt-bigquery` as a main dependency, Terraform IaC provisioning 6 datasets, GitHub Actions workflow for scheduled builds.
- **Security CI** — bandit (Python SAST), pip-audit (dependency CVEs), gitleaks (full-history secret scan) on every PR. Currently: 0 issues / 0 CVEs.

## Tech stack

| Tool | Role | Why chosen |
|------|------|------------|
| **dbt-core 1.11+** | SQL transformation layer | Contracts, MetricFlow integration, native DuckDB support |
| **DuckDB 1.2+** | Dev warehouse | Zero-infra, embedded, fast local iteration |
| **BigQuery** | Prod warehouse | Scalable managed SQL; Terraform-provisioned |
| **Python 3.12+** | Data generator + backtest + orchestration | Type-safe, uv-managed, testable in isolation |
| **Dagster** | Orchestration | Asset-centric model makes data lineage and quality gates first-class |
| **MetricFlow** | Semantic layer | Single metric definition; prevents drift between teams and tools |
| **Elementary** | Observability | dbt-native anomaly/schema monitoring, HTML report artifact |
| **PyIceberg** | Iceberg landing zone | Open table format, time travel, metadata-only schema evolution |
| **Evidence** | BI-as-code | SQL + markdown, version-controlled dashboard, no BI server required |
| **Terraform** | IaC | Reproducible BigQuery dataset provisioning |
| **uv** | Package management | Fast, lockfile-enforced, deterministic installs |
| **Ruff + SQLFluff** | Linting | Python (ruff) + SQL (sqlfluff, dbt templater) in CI |
| **bandit + pip-audit + gitleaks** | Security CI | SAST + dependency CVEs + secret scan on every PR |

## Results

| Metric | Value |
|--------|-------|
| Loan book generation | 12,000 loans / 255,131 performance rows in ~2.3 s |
| dbt models | 28 models (3 staging + 13 intermediate + 9 DWH + 3 risk mart + 2 finance mart) |
| dbt data tests | 333 in full build; all 14 models under contract |
| Custom singular invariant tests | 35 (9 DWH + 10 risk + 13 ECL + 3 staging) — all kill-tested |
| pytest tests | 441 across generator, backtest, dbt integration, orchestration, semantic layer, Iceberg |
| Full CI runtime | ~100 s end-to-end (lint + generate + pytest + dbt builds + semantic validate + Dagster materialize) |
| Dagster assets | 65 (35 credit-platform + 30 Elementary) via one `@dbt_assets` |
| Dagster asset-check gates | 3 custom (2 ERROR-blocking + 1 WARN) + every dbt schema test surfaced as a check |
| Full Dagster materialization | 465 nodes PASS / 0 ERROR |
| Elementary observability | 4 monitors, 400 captured test results, 7.4 MB `edr report` HTML artifact |
| Governed metrics | 7 — all values pinned (full-precision) and kill-tested |
| ECL allowance rows | 48,000 (12,000 loans × 4 scenarios) |
| ECL probability-weighted total | ~$1.4 M (11,036 Stage 1 / 191 Stage 2 / 773 Stage 3 loans) |
| Iceberg time travel | Write 12K → append 12K → `iceberg_scan(snapshot_from_id=first)` returns exactly 12K |
| Security scanners | bandit 0 issues · pip-audit 0 CVEs · gitleaks full-history clean |
| License | Apache-2.0 |

## Quickstart

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 18+ (Evidence dashboard only).

```bash
git clone https://github.com/OmerTDK/credit-data-platform
cd credit-data-platform
uv sync

# Generate the synthetic loan book (fixed seed, reproducible in ~2.3 s)
make generate

# Build and test the complete dimensional warehouse
make dbt-build-dwh

# Run the full test suite (441 pytest tests)
make test

# Materialize everything through Dagster and run the quality-gate asset checks
uv run dbt deps
make dagster-materialize

# Browse the asset graph and quality gates in the Dagster UI
make dagster-dev

# Validate and query the MetricFlow semantic layer
make dbt-build-semantic
make semantic-validate
make semantic-query

# Generate the Elementary observability HTML report
make elementary-report

# Run security scanners (bandit + pip-audit)
make security

# Run the full CI suite (matches GitHub Actions exactly)
make ci
```

## Project structure

```
credit-data-platform/
├── src/
│   ├── loanbook/           # Synthetic generator: state machine, calibration, Iceberg writer
│   ├── ecl_backtest/       # IFRS 9 backtest over 8 quarterly dates + parameter validation
│   └── orchestration/      # Dagster definitions, @asset_check quality gates, materialize runner
├── models/
│   ├── staging/            # stg_loanbook__{entity}.sql — typed views over landing parquet
│   ├── intermediate/       # Business logic, SCD2 prep, ECL components, roll-rate observations
│   ├── dwh/                # 4 conformed dims + SCD2 + event stream + 3 facts (all contracted)
│   ├── marts/
│   │   ├── risk/           # Roll-rate matrix, vintage curves, prepayment speed (CPR/SMM)
│   │   └── finance/        # IFRS 9 ECL allowance + summary (3 scenarios + probability-weighted)
│   ├── semantic/           # MetricFlow semantic models + 7 governed metric definitions
│   └── metricflow/         # MetricFlow time spine
├── tests/
│   ├── dbt/                # 35 custom singular SQL tests (invariants no generic test can express)
│   ├── test_dbt_*.py       # dbt integration tests (row counts, data invariants per layer)
│   ├── test_semantic_layer.py  # Metric value pins — all 7 metrics, full precision
│   ├── test_evidence_dashboard.py  # Evidence source query coverage — no Node/network
│   ├── test_iceberg.py     # Iceberg time travel + schema evolution end-to-end
│   └── test_orchestration_*.py  # Dagster definitions, check logic, materialize runner
├── seeds/                  # ECL parameter tables (LGD, EAD/CCF, scenario weights, watchlist)
├── bi/                     # Evidence BI-as-code dashboard (4 pages, SQL + markdown)
├── terraform/              # BigQuery dataset provisioning + optional IAM bindings
├── docs/
│   ├── adr/                # 14 Architecture Decision Records (ADR-0000 through ADR-0013)
│   └── calibration-sources.md  # Published data sources anchoring hazard rates
├── .github/workflows/
│   ├── ci.yml              # Lint + test + dbt builds + semantic validate + Dagster + Elementary
│   ├── dbt-prod.yml        # Scheduled BigQuery prod runs (daily cron)
│   └── docs.yml            # dbt docs site publish
├── dbt_project.yml         # Layer schema mapping: stg / int / dwh / mart_risk / mart_finance
├── pyproject.toml          # Python deps (uv), ruff config, bandit config
├── profiles.yml            # DuckDB dev + BigQuery prod targets
└── Makefile                # All dev workflows (`make help` for full list)
```

## Design decisions

All major decisions are documented in [docs/adr/](docs/adr/) with explicit trade-off analysis.

| ADR | Decision |
|-----|----------|
| [0001](docs/adr/0001-dual-target-warehouse.md) | DuckDB (dev) + BigQuery (prod) dual-target |
| [0002](docs/adr/0002-synthetic-generator-architecture.md) | State-machine generator with calibrated hazard rates |
| [0003](docs/adr/0003-external-parquet-sources-and-schema-mapping.md) | External parquet sources via dbt-duckdb `external_location` |
| [0004](docs/adr/0004-multi-product-extension.md) | Multi-product extension (auto, mortgage, credit card) |
| [0005](docs/adr/0005-dimensional-layer-and-event-sourced-loan-state.md) | Immutable event stream + derived current state (vs. mutable column) |
| [0006](docs/adr/0006-risk-marts-methodology.md) | Roll-rate denominator, vintage MOB spine, SMM/CPR formula |
| [0007](docs/adr/0007-ifrs9-ecl-methodology.md) | Markov PD term structure, 3 SICR triggers, scenario weighting, Python backtest |
| [0008](docs/adr/0008-orchestration-dagster-asset-centric.md) | Asset-centric orchestration with Dagster + dagster-dbt |
| [0009](docs/adr/0009-observability-elementary.md) | Data observability with Elementary (anomaly monitors + HTML report) |
| [0010](docs/adr/0010-security-ci-layer.md) | Security CI layer (bandit + pip-audit + gitleaks) |
| [0011](docs/adr/0011-semantic-layer-and-evidence-dashboard.md) | MetricFlow on DuckDB + Evidence dashboard |
| [0012](docs/adr/0012-iceberg-landing-zone.md) | Apache Iceberg landing zone with time travel + schema evolution |
| [0013](docs/adr/0013-bigquery-terraform.md) | BigQuery prod target + Terraform IaC |

### The hardest call: event-sourced loan state

Loan state (delinquency bucket, lifecycle status) could be stored as one mutable row per loan, overwritten monthly. Simpler — but it destroys history. "What was this loan's delinquency bucket three months ago?" then requires a separate snapshot or audit table that inevitably drifts from the source.

The path taken: an immutable event stream (`fct_loan_state_event`, 21,320 rows) where every state transition is recorded as a fact. Current state (`dim_loan_current_state`) is derived deterministically from the stream via window functions, never stored directly. A singular dbt test replays the events independently and asserts equivalence with the derived dimension.

Why this was the harder choice:

1. **Performance contract.** Deriving current state from a stream is a window-function scan over event history. On 12K loans / 21K events: milliseconds. On a 10M-loan production book: a design constraint that forces explicit partitioning decisions. That tradeoff is committed to at schema design time.
2. **Downstream join complexity.** Every model that needs current state joins to the derived dimension — risk marts, ECL staging, semantic layer. A mutable-column design would be a simpler LEFT JOIN.
3. **Testing burden.** The immutable-stream contract requires a singular test that doesn't exist in a mutable-column world.

The payoff: point-in-time correctness is structural. The roll-rate matrix reads prior-period state directly from the event stream with no time-travel workaround. The SCD2 borrower dimension (19,257 version rows across 12,000 borrowers, tracking worst-delinquency-across-loans over time) is computable only because the event stream makes version boundaries explicit.

See [ADR-0005](docs/adr/0005-dimensional-layer-and-event-sourced-loan-state.md) for the full analysis.

## License

Apache-2.0. See [LICENSE](LICENSE).
