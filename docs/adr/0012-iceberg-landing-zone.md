# ADR-0012: Apache Iceberg landing zone alongside Parquet

**Status:** Accepted
**Date:** 2026-06-19
**Phase:** 7

---

## Context

The platform's data landing zone writes raw Parquet files via PyArrow
(`src/loanbook/output.py`). DuckDB reads them in place through
`external_location: read_parquet(...)` in the dbt source config. This is
simple and fast, but Parquet-on-filesystem offers none of the capabilities a
modern lakehouse format provides:

- **No time travel.** Once a file is overwritten, the previous state is gone.
  A data-quality investigation cannot ask "what did this table look like
  yesterday?" without a separate backup.
- **No schema evolution.** Adding a column requires rewriting every data file.
  A downstream schema contract that expects the new column blocks until the
  full dataset is rewritten.
- **No snapshot isolation.** A concurrent reader can see a partially-written
  landing zone if the generator crashes mid-write.

Apache Iceberg solves all three with an open table format layered on top of
Parquet data files. DuckDB 1.5.3 (the project's pinned version) includes a
mature Iceberg extension with read support via `iceberg_scan()`, time-travel
via `snapshot_from_id` / `snapshot_from_timestamp`, and `iceberg_snapshots()`
/ `iceberg_metadata()` for inspection.

The question is whether Iceberg adds enough value to justify the extra
dependency and complexity in a synthetic-data portfolio project.

---

## Decision

Add an **Iceberg landing zone** alongside the existing Parquet landing zone,
using **PyIceberg with a local SQLite catalog** — zero external infrastructure.

### Architecture

```
make generate  →  data/landing/  (Parquet, unchanged)
                       ↓
              src/loanbook/iceberg.py  →  data/iceberg/  (Iceberg tables)
                       ↓
              DuckDB iceberg_scan()  ←  tests/test_iceberg.py
```

- **PyIceberg** (`pyiceberg[sql-sqlite,pyarrow]`) writes Arrow tables into
  Iceberg tables backed by a SQLite catalog at `data/iceberg/catalog.db`.
  The catalog and all data files are local — no object store, no REST
  catalog server, no credentials.
- **`src/loanbook/iceberg.py`** provides: `write_table_iceberg()` (create or
  overwrite), `append_to_table()` (new snapshot), `evolve_schema_add_column()`
  (metadata-only column add), plus snapshot and metadata inspection helpers.
- **DuckDB** reads Iceberg tables through `iceberg_scan(metadata_path)` with
  full time-travel support (`snapshot_from_id`).
- **11 pytest tests** exercise the real capabilities: write + read, time
  travel (query historical snapshot returns original row count), schema
  evolution (new column reads NULL on existing rows, no data rewrite),
  overwrite idempotency, data integrity across snapshots, DuckDB snapshot
  inspection.

### What the dbt pipeline uses

The dbt staging layer continues to read from the Parquet landing zone
(`data/landing/`). The Iceberg integration is a **parallel landing zone**
that demonstrates the lakehouse pattern. The dbt sources are not switched to
Iceberg because:

1. `dbt-duckdb`'s `external_location` macro uses `read_parquet()`, not
   `iceberg_scan()`. Switching would require a custom materialization or a
   pre-hook SQL block with `iceberg_scan()` — added complexity for no
   pipeline benefit on a local synthetic dataset.
2. The value of Iceberg in this project is the **demonstrated capability**
   (time travel, schema evolution, snapshot isolation), not a migration of the
   existing pipeline. The tests prove the capabilities are real.

### Why the Iceberg integration is real, not a checkbox

- Time travel is exercised end-to-end: write 12K rows → append 12K more →
  DuckDB `iceberg_scan(snapshot_from_id=first)` returns exactly 12K.
- Schema evolution is exercised end-to-end: add a `risk_tier` column
  metadata-only → DuckDB reads all 12K existing rows with NULL for the new
  column → no data files rewritten (snapshot count unchanged).
- DuckDB's `iceberg_snapshots()` returns real snapshot metadata.
- The PyIceberg SQLite catalog is the same catalog implementation used in
  local development with tools like Spark, Trino, and Polaris — it is not
  a mock.

---

## Alternatives considered

**Switch dbt sources to Iceberg.** Rejected — `dbt-duckdb` has no native
`iceberg_scan()` source integration; the workaround (pre-hook SQL creating a
view from `iceberg_scan()`) is fragile and gains nothing for a local
synthetic dataset. The Parquet sources work, and the Iceberg capabilities are
proven by the test suite.

**Use DuckDB's catalog-attached Iceberg (ATTACH TYPE iceberg).** Requires a
REST Catalog server — an external dependency that breaks CI's zero-
infrastructure guarantee. The PyIceberg SQLite catalog provides the same
Iceberg table format without a server.

**Use DuckLake instead of Iceberg.** DuckLake is DuckDB-native and avoids the
separate catalog. Rejected because Iceberg is the industry-standard open
table format — demonstrating Iceberg proficiency is the portfolio signal,
not DuckDB-specific features.

**Skip Iceberg entirely.** The brief calls for demonstrating production-grade
data engineering. A lakehouse format with time travel and schema evolution is
table stakes for any modern data platform. Skipping it leaves a gap in the
portfolio narrative.

---

## Consequences

**Easier:**

- The project demonstrates real Iceberg time travel and schema evolution —
  capabilities interviewers and reviewers expect a staff-level AE to know.
- The PyIceberg + SQLite catalog pattern is reusable: any team can adopt it
  for local Iceberg development without standing up infrastructure.

**Harder / committed to:**

- One more dependency (`pyiceberg[sql-sqlite,pyarrow]`). Adds ~5 packages to
  the lock file. Acceptable for a project that already carries dbt, Dagster,
  Elementary, and MetricFlow.
- `data/iceberg/` is gitignored and regenerated on demand. Tests use
  `tmp_path` fixtures so they are isolated.

**Not changed:**

- The dbt pipeline still reads Parquet. The Iceberg landing zone is additive.
- CI stays network-free. PyIceberg's SQLite catalog is local-only.
