# ADR-0008: Asset-centric orchestration with Dagster + dagster-dbt

**Status:** Accepted
**Date:** 2026-06-14
**Phase:** 5

---

## Context

Through Phase 4 the platform was driven entirely by a `Makefile`: `make generate`
writes the landing parquet, then a chain of `dbt build --select ...` targets
builds staging -> intermediate -> dwh -> risk -> ECL, and pytest fixtures shell
out to `dbt build` to exercise each layer. This works, but it has no model of the
data assets themselves — the unit of work is "run this dbt command", not "this
table is fresh and correct". There is no lineage graph, no per-asset status, and
no place to attach a quality gate that blocks downstream work when an upstream
table is wrong.

Phase 5 needs three things the Makefile cannot express cleanly:

1. A first-class **asset graph** — every dbt model as a node with lineage.
2. **Quality gates** that gate *real* conditions and can carry severity
   (ERROR vs WARN), evaluated as part of materialization, not as an afterthought.
3. A materialization path that still runs dbt as a **managed subprocess** (the
   repo's hard rule: never a bare shell `dbt build`).

The motivating regression: ADR-0007 documents that a naive single-step PD formula
zeroes out Stage 1 and Stage 2 ECL. That class of bug — the performing book
silently carrying no loss allowance — passes every generic `not_null`/`unique`
test. It needs a semantic gate that is CI-enforced.

---

## Decision: expose the dbt project as Dagster software-defined assets

Use **Dagster** (`dagster` + `dagster-dbt`) with the asset-centric model:

- A single `@dbt_assets` definition over the dbt `manifest.json` turns all 28 dbt
  models (plus seeds and sources) into Dagster assets. The default
  `DagsterDbtTranslator` keys each asset by its schema path
  (`mart_finance/mart_finance_ecl_summary`, `dwh/fct_payment`, …).
- Materialization runs `dbt build` through **`DbtCliResource`** — a managed
  subprocess, streamed back into Dagster as asset materializations and (for every
  dbt schema test) asset-check evaluations. This satisfies the "no bare shell
  `dbt build`" rule: the only `dbt` invocation is the one Dagster owns.
- Three custom `@asset_check` gates are attached to the ECL marts via
  `get_asset_key_for_model`:
  - `ecl_stage_ecl_strictly_positive` (**ERROR**, blocking) — Stage 1 and Stage 2
    portfolio ECL must be strictly positive in *every* scenario. This is the
    ADR-0007 regression, now CI-enforced.
  - `facts_resolve_to_dim_loan` (**ERROR**, blocking) — every loan_id in
    `fct_payment`, `fct_loan_state_event`, and `mart_finance_ecl_allowance`
    resolves to `dim_loan`.
  - `ecl_allowance_volume_within_band` (**WARN**, non-blocking) — the ECL
    allowance row count (48,000 = 12,000 loans × 4 scenarios) sits inside a
    sanity band.
- The check *logic* lives in pure functions in `orchestration/checks.py` (queries
  over the built DuckDB), so each gate is unit-testable and kill-testable without
  spinning up a Dagster run. The `@asset_check` bodies are thin adapters.

`make dagster-materialize` runs the implicit global asset job in-process; it is
wired into CI after the scoped dbt builds. An ERROR gate failing fails the run,
which fails CI.

---

## Alternatives considered

**Keep the Makefile + add bespoke check scripts.** Rejected. We would reinvent an
asset graph, severity levels, and run status by hand, and the gates would be
detached from the build rather than part of it. The Makefile stays as the
ergonomic local entrypoint, but it now *delegates* the asset run to Dagster.

**dbt Cloud / GitHub Actions cron.** Rejected for the portfolio signal: cron
schedules a command; it does not model assets, lineage, or gated checks. The
brief explicitly calls out Dagster as the maturity signal.

**Airflow.** Rejected. Task-centric, not asset-centric; heavier operationally; no
native dbt-asset or asset-check model without significant glue.

**Write the gates as dbt singular tests instead of asset checks.** Partially
done — the platform already has 35 singular dbt tests. But the three new gates
benefit from Dagster severity (WARN vs ERROR) and from being expressible as
plain Python over the warehouse (the volume band, the multi-relation referential
sweep), which keeps them readable and independently testable.

---

## Consequences

**Easier:** every model is a visible asset with lineage; gates are first-class,
severity-tagged, and block downstream work; `dagster dev` gives a browsable graph;
the gate logic is plain Python with its own unit + kill tests.

**Harder / committed to:** two new runtime dependencies (`dagster`,
`dagster-dbt`) and a `dagster-webserver` dev dependency; the manifest must exist
before the asset graph loads (`DbtProject.prepare_if_dev()` handles this); the
full Dagster materialization rebuilds the whole project, so it is the heaviest
CI step (~50–60 s of the ~100 s end-to-end run).

**Boundary with the hard rule:** the *only* sanctioned `dbt build` is the one
`DbtCliResource` runs inside Dagster. Scoped `dbt build --select ...` calls remain
in the Makefile and pytest fixtures for fast per-layer feedback; they are not
bare shell builds of the whole project.
