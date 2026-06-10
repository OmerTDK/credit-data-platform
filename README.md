# credit-data-platform

Multi-product consumer-credit data platform: calibrated synthetic loan book, dimensional + event-sourced dbt warehouse, IFRS 9 ECL, semantic layer, observability

> Status: 🚧 under construction — not yet at definition-of-done.

Phase 1 done: seeded synthetic loan-book generator (`loanbook`, all four products — personal loans, auto loans, mortgages, credit cards) — delinquency state machine with validated transitions, per-product calibration anchored to published statistics ([sources](docs/calibration-sources.md)), byte-identical parquet from a fixed seed (12,000 accounts / 255,131 monthly rows / 9.3 MB in ~2.3 s via `make generate`) — see [ADR-0002](docs/adr/0002-synthetic-generator-architecture.md) and [ADR-0004](docs/adr/0004-multi-product-extension.md). Phase 0: dbt skeleton, DuckDB dev target, CI gates (`dbt parse`, SQLFluff); BigQuery prod target pending — see [ADR-0001](docs/adr/0001-dual-target-warehouse.md).

## Why this exists

<!-- System narrative: the problem, why it is interesting, what it demonstrates. -->

## Architecture

<!-- Diagram + one paragraph per component. -->

## Results

<!-- Quantified outcomes: runtime, cost, test count, data volumes. Real numbers only. -->

## Design decisions

See [docs/adr/](docs/adr/) — each major decision documented with its trade-offs.

## Quickstart

<!-- Reproducible setup: clone → install → run end-to-end. -->

## Standards

Engineering conventions in [standards/](standards/) govern all code in this repo.
