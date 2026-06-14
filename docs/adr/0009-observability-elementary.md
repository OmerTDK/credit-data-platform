# ADR-0009: Data observability with Elementary

**Status:** Accepted
**Date:** 2026-06-14
**Phase:** 5

---

## Context

The platform has strong *correctness* testing — enforced dbt contracts, 35 custom
singular invariant tests, and now three Dagster asset-check gates. What it lacked
was *observability*: a record of test-result history, table volume over time, and
schema drift that a reviewer can browse without reading the warehouse. The brief
requires a real observability artifact — "test-results / freshness / volume
anomaly" — that produces actual output, not a checkbox.

---

## Decision: the Elementary dbt package + edr report

Add **Elementary** (`elementary-data/elementary` dbt package, pinned to `0.24.0`
— the latest release compatible with dbt-core 1.11) plus the matching **`edr`
CLI** (`elementary-data[duckdb]`, same minor) as a dev dependency.

- Elementary's `on-run-end` hooks capture every dbt test result, run result, and
  artifact into a dedicated `elementary` schema during a normal `dbt build`.
- Two key models carry real Elementary anomaly monitors, declared in their dbt
  YAML at WARN severity:
  - `fct_payment` — `elementary.volume_anomalies` time-bucketed by
    `report_month` (monthly row-count monitoring across 35 months) +
    `elementary.schema_changes`.
  - `mart_finance_ecl_summary` — `elementary.volume_anomalies` (total row count)
    + `elementary.schema_changes`.
- `make elementary-report` runs `edr report` against the captured `elementary`
  schema and writes `artifacts/elementary_report.html` — a self-contained
  observability report (~7.4 MB) embedding 400 captured test results and the
  volume-monitoring metrics. CI generates it on every PR and uploads it as a
  build artifact.

**Capture is gated by an env var.** Elementary's `on-run-end` result-capture is
disabled by default (`disable_run_results` / `disable_tests_results` /
`disable_dbt_*_autoupload` keyed on `env_var('ELEMENTARY_CAPTURE', '0')`), and the
anomaly/schema tests are tagged `elementary`. The scoped per-layer dbt builds
(`dbt-build-dwh/risk/ecl`) therefore neither require the Elementary model layer
nor pay its cost — they exclude `tag:elementary` and run with capture off. Only
the full Dagster materialization exports `ELEMENTARY_CAPTURE=1`, which builds the
Elementary models and captures results so the report has data.

---

## Alternatives considered

**dbt's native `source freshness` + the `elementary` hooks off.** Rejected — no
volume/schema-anomaly history and no browsable report; freshness alone is thin on
a from-seed synthetic book where every build is "fresh".

**re_data.** Rejected — smaller community, weaker dbt-native integration than
Elementary, and the brief names Elementary specifically.

**A hand-rolled metrics table + a static HTML page.** Rejected as reinvention:
Elementary already models test results, run results, and anomaly metrics, and
ships a maintained report generator.

**Pin to the newest Elementary (0.24.1 package).** Rejected — the dbt *package*
caps at `0.24.0` for dbt-core 1.11; 0.24.1 is the CLI-only patch. Pinning the
package to 0.24.0 and the CLI to the same minor keeps them in lockstep.

---

## Consequences

**Easier:** a single `make elementary-report` produces a real, shareable
observability artifact; volume and schema monitors accrue history as the project
runs; the report is published from CI on every PR.

**Harder / committed to:** Elementary overrides dbt's built-in test
materialization (the `require_explicit_package_overrides_for_builtin_materializations: false`
flag is required on dbt ≥ 1.8); the `elementary` profile needs an absolute
DuckDB path because `edr` runs from its own internal project directory (provided
via `CREDIT_PLATFORM_DUCKDB`); anomaly tests only *flag* once enough history
exists, so on a from-clean build they pass on insufficient data — they still run,
store metrics, and gate schema drift immediately.
