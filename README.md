# credit-data-platform

Multi-product consumer-credit data platform: calibrated synthetic loan book, dimensional + event-sourced dbt warehouse, IFRS 9 ECL, semantic layer, observability

> Status: 🚧 under construction — not yet at definition-of-done.

Phase 0 done: dbt skeleton (dbt-core, DuckDB dev target via committed `profiles.yml`), CI gates for `dbt parse` and SQLFluff (duckdb dialect, dbt templater). BigQuery prod target pending — see [ADR-0001](docs/adr/0001-dual-target-warehouse.md).

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
