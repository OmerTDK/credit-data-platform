# ADR-0003: External parquet sources and per-layer schema mapping

**Date:** 2026-06-10
**Status:** Accepted

## Context

Phase 2a puts dbt on top of the generated loan book. Two decisions are forced
before the first staging model exists:

1. **How dbt reads the landing zone.** The generator writes parquet to
   `data/landing/` (gitignored, seed-reproducible, 6.5 MB at the default
   volume): one file each for loans and borrowers, and monthly performance
   hive-partitioned by `report_year_month`. dbt needs these as sources.
2. **Where models land.** The standards mandate one schema per layer
   (`stg`, `int`, `dwh`, `mart_{domain}`), but dbt's default
   `generate_schema_name` concatenates the target schema with any custom
   schema — on the DuckDB dev target that yields `main_stg`, not `stg`.

A related naming wrinkle: standards name staging *relations*
`{source}__{entity}` (the schema already says "staging"), while staging
*files* are `stg_{source}__{entity}.sql` — so the model name and the
relation name must diverge.

## Decision

**Sources: external parquet via dbt-duckdb `external_location`.** The
`loanbook` source sets
`meta: external_location: "read_parquet('data/landing/{name}/*.parquet')"`,
and `monthly_performance` overrides it at table level with
`read_parquet(..., hive_partitioning = true)` over the partition glob.
DuckDB queries the parquet directly; nothing is copied into the warehouse
file, so regenerating the book invalidates nothing. Source freshness is
intentionally not configured: the landing zone is a static snapshot
regenerated wholesale, so a loaded-at freshness check has no meaning.

**Schema mapping: `+schema` per layer plus a `generate_schema_name`
override.** `dbt_project.yml` assigns `stg` / `int` / `dwh` / `mart_risk` /
`mart_finance` per model folder, and the override returns the custom schema
name verbatim (falling back to the target schema when none is set). Layers
land in schemas named exactly per the standards on every target.

**Relation naming: explicit `alias` per staging model.** Each staging model
sets `config(alias='loanbook__{entity}')`, so the warehouse relation is
`stg.loanbook__loan` while the model file stays `stg_loanbook__loan.sql`. An
alias-generating macro that strips layer prefixes was rejected: marts keep
their prefix by convention, so a generic macro needs per-layer cases —
explicit one-line aliases are simpler and visible at the top of each model.

## Alternatives considered

- **dbt seeds.** Seeds are CSV-only, slow at 215k rows, and would put
  generated data into git that the generator already reproduces from a seed
  byte-identically. Lost on format, scale, and redundancy.
- **Loading parquet into the DuckDB file first** (a pre-dbt load script or
  dbt-duckdb plugin materialization). Adds an ELT step and a second copy of
  the data that can silently drift from the landing zone; DuckDB reads
  parquet natively at query speed, so the copy buys nothing at this volume.
  Lost on state duplication.
- **dbt-duckdb `register_upstream_external_models` / model-level external
  materializations.** Solves writing *out* to parquet, not reading in;
  irrelevant to a landing-zone source. Lost on fit.
- **Default schema names (`main_stg`).** Works without a macro but violates
  the standards' layer-schema contract and diverges from the BigQuery dataset
  layout the project will deploy to. Lost on convention.

## Consequences

- `external_location` paths are relative, so every dbt invocation must run
  from the repo root — already true for the Makefile, CI, and the pytest
  gates, all of which set `DBT_PROFILES_DIR=.` there. The staging views
  embed those relative paths and are only queryable from the repo root.
- The source definition is DuckDB-specific. When the BigQuery prod target
  lands (ADR-0001), the landing zone gets loaded into a `raw` dataset and the
  source definition becomes target-aware — accepted open item, consistent
  with ADR-0001's deferral of everything BigQuery.
- CI now generates the loan book (`make generate`, fixed seed, ~1.5 s) before
  the dbt steps, so `dbt build --select staging` exercises models and data
  tests against real rows on every PR, and SQLFluff lints real model SQL.
- Every future layer folder needs only a `+schema` line in
  `dbt_project.yml`; the override applies project-wide.
