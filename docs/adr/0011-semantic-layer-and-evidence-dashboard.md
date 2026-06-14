# ADR-0011: Semantic layer (MetricFlow) + Evidence BI-as-code dashboard

**Status:** Accepted
**Date:** 2026-06-14
**Phase:** 6

---

## Context

The platform's metrics (default rate, prepayment speed, portfolio yield, vintage
loss curve, …) are currently re-derived ad hoc wherever they are needed — in the
risk marts, in the ECL layer, and (soon) in two downstream portfolio projects:
the OSS dbt package that extracts these risk marts, and the **llm-analyst** that
answers natural-language questions over this book. If each consumer re-implements
"default rate," they will drift. Brief §3 calls for a semantic layer where
"metrics are defined once and shared by BI tools and an API," and lists "metrics
live in the semantic layer, never hardcoded in BI" as an ADR seed.

This phase delivers two things on top of the existing dwh/marts:

1. A **governed semantic layer** — metrics defined once, queryable locally, with
   pinned values so a definition change is caught in CI.
2. A **BI-as-code dashboard** that ships in the repo and builds to a static site.

Both must run against the local **DuckDB** target. The BigQuery prod target is
still deferred (ADR-0001), so the semantic layer and dashboard must work
end-to-end on DuckDB alone.

---

## Decision

### Semantic layer: dbt Semantic Layer / MetricFlow on DuckDB

Use **MetricFlow** (the open-source engine behind the dbt Semantic Layer) via the
`dbt-metricflow` package, defining semantic models + metrics as dbt YAML under
`models/semantic/` and a `metricflow_time_spine` model under `models/metricflow/`.
Metrics are queried locally with `mf query` / `mf validate-configs`.

**The MetricFlow–DuckDB finding (verified, not assumed).** The dbt docs FAQ lists
the supported Semantic Layer platforms as Snowflake, BigQuery, Databricks,
Redshift, Postgres, and Trino — DuckDB is absent. That FAQ describes the **hosted
dbt Cloud Semantic Layer** (the GraphQL/JDBC API tier), not the open-source `mf`
CLI. The open-source CLI **does** support DuckDB: `dbt_metricflow`'s
`SupportedAdapterTypes.DUCKDB` maps to `SqlEngine.DUCKDB` with a dedicated
`DuckDbSqlPlanRenderer`, the bundled `mf tutorial` project ships a `type: duckdb`
profile, and `mf validate-configs` + `mf query` run green against our warehouse.
So `metricflow_duckdb_supported = true` for local development. What is *not*
available on DuckDB is the hosted Semantic Layer API — that arrives only with a
supported cloud warehouse (i.e. when the BigQuery target lands).

**Seven governed metrics** are defined once and shared:

| Metric | Type | Source semantic model | Definition |
|---|---|---|---|
| `origination_volume` | simple | `loan_originations` (`fct_loan_origination`) | SUM(principal_amount) |
| `default_rate` | ratio | `loan_lifecycle` (`fct_loan_lifecycle`) | defaulted_loans / lifecycle_loans |
| `delinquency_rate` | ratio | `loan_payments` (`fct_payment`) | delinquent_loan_months / loan_months |
| `portfolio_yield` | ratio | `loan_payments` | interest_charged / beginning_balance |
| `avg_balance` | simple (avg) | `loan_payments` | AVG(ending_balance_amount) |
| `cpr` | derived | `prepayment_speed` (`mart_risk_prepayment_speed`) | 1 − (1 − smm)¹² |
| `vintage_loss_curve` | ratio | `vintage_curve` (`mart_risk_vintage_curve`) | cumulative_defaults / cohort_exposure |

Dimensions / entities: **vintage** (origination cohort quarter), **product**,
**credit_tier** (score band), **delinquency_status**, and `months_on_book` on the
cohort marts. Geography is intentionally omitted — the synthetic book has no
geography attribute (the standards' DE/AT split is illustrative, not a column on
these facts). `default_rate` (defined on the lifecycle model) is groupable by
`credit_tier` (defined on the originations model) through the shared `loan`
entity — the cross-model join is the whole point of a semantic layer.

**All 7 governed metric values are pinned** (`tests/test_semantic_layer.py`),
each cross-checked against an independent direct DuckDB derivation so the pins
cannot go stale: `origination_volume = 430,503,900.00` (to the cent, via
`mf query --csv`; SUM over 5,397 amortizing loans — credit cards carry NULL
`principal_amount`), `default_rate = 0.055` (660 / 12,000; component metrics
`defaulted_loans` and `lifecycle_loans` pinned separately to catch
denominator-source swaps), `cpr` (book-level 1 − (1−SMM)¹²; exponent mutant
caught), `portfolio_yield`, `delinquency_rate`, `avg_balance`, and
`vintage_loss_curve`. Kill-test verified (manual, one-time): mutating
`origination_principal` to `principal_amount + 1` fails the `origination_volume`
pin. The pin tests are the repeatable CI gate for all 7 metrics.

### BI: Evidence (evidence.dev), built to a static site, query layer gated in CI

Use **Evidence** for the dashboard: SQL + markdown pages under `bi/`, a DuckDB
source pointed at the dbt-built warehouse, compiled to a static site with
`evidence build`. Four pages: **portfolio overview**, **vintage curves**,
**risk-cohort drill-down**, and a **FinOps / cost** view.

The FinOps view uses a **rows × columns ("cells") proxy** from `duckdb_tables()`
— DuckDB has no per-query billing, so the materialized footprint stands in for
what each model would cost to store and scan on a metered warehouse. When the
BigQuery target lands it swaps to `INFORMATION_SCHEMA.JOBS` real spend.

**CI is kept network-free.** `evidence build` is a Node/npm step (≈1,300
packages, a 2-minute install) — too heavy and flaky for the Python CI. Instead:

- The full `evidence build` is proven locally and wired as `make evidence-build`
  / `make evidence-install` (documented, run on demand).
- CI covers the **query layer** with `tests/test_evidence_dashboard.py`: every
  Evidence source query executes against the warehouse, every page references
  only source queries that exist, and the connection points at the warehouse. A
  dwh/mart column renamed out from under the dashboard fails CI without Node.

### Target: DuckDB only — BigQuery + Terraform IaC still deferred

This phase targets **DuckDB only**, consistent with ADR-0001. The BigQuery prod
target and Terraform IaC remain **deferred**, blocked on the open GCP-account
question. No BigQuery semantic-layer target or Terraform is invented here. When
the account question resolves, the hosted dbt Semantic Layer API and a real
BigQuery cost view become available on top of the same metric definitions.

---

## Alternatives considered

**Cube instead of MetricFlow.** Cube is a strong semantic layer with a first-class
API and DuckDB support. Rejected for this repo because the metrics already live in
a dbt project: MetricFlow keeps the definitions *in dbt*, versioned beside the
models they aggregate, with no second service to run. The brief explicitly names
"dbt Semantic Layer / MetricFlow, or Cube" — MetricFlow is the lower-friction fit
for a dbt-native warehouse.

**Force the hosted dbt Semantic Layer onto DuckDB.** Not possible — the hosted
API requires a supported cloud warehouse. Forcing it would mean standing up the
BigQuery target first, which is deferred. The open-source `mf` CLI gives the full
define-once / query-locally loop on DuckDB today.

**Metabase / Qlik instead of Evidence.** Both are server BI tools, not BI-as-code:
they store dashboards in a database, not in the repo, and can't build to a static
site in CI. Evidence ships the dashboard *as code* (SQL + markdown, version
controlled), which is the senior signal the brief asks for and is reviewable in a
PR. Metabase/Qlik remain options once a hosted warehouse exists.

**Run `evidence build` in CI.** Rejected — a ~1,300-package npm install on every
PR is slow and network-fragile, and the Python CI has no Node toolchain. The
query-layer test gives the high-value guarantee (the SQL still resolves against
the warehouse) without the toolchain or the network.

**Materialize metrics as dbt models instead of a semantic layer.** That is what
the risk marts already do for the *cohort* views. A semantic layer adds the
define-once-query-many-ways capability (any metric × any dimension, joined across
models on shared entities) that a fixed mart table cannot, and is what the
llm-analyst will sit on.

---

## Consequences

**Easier:**

- Metrics are defined once; BI (Evidence) and the future API/llm-analyst share one
  definition. No more re-deriving "default rate" per consumer.
- A metric-definition change that moves a number is caught in CI by the pinned
  tests — the anti-drift guarantee the brief asks for.
- The dashboard is reviewable as code in a PR and builds to a static site any host
  can serve.

**Harder / committed to:**

- One more toolchain in dev deps (`dbt-metricflow`) and one Node project (`bi/`).
  The Node project is not in `make ci`, so CI stays Python-only and network-free.
- dbt-core enforces globally-unique (primary entity, dimension name) pairings; two
  semantic models on the same `loan` primary entity may not both define a
  same-named dimension. Resolved by naming the lifecycle model's local time
  dimension distinctly and reaching shared dimensions through the entity join.
- The semantic layer and the hand-written Evidence source queries both encode the
  same metric arithmetic; they are kept in agreement by the pinned semantic tests
  plus the page comments that point back to the metric names. When the API tier
  lands, the Evidence queries should move onto it to remove the duplication.

**Deferred (unchanged from ADR-0001):** BigQuery prod target, Terraform IaC, the
hosted dbt Semantic Layer API, and a real BigQuery cost-attribution view — all
blocked on the open GCP-account question.
