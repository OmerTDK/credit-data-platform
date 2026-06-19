# ADR-0013: BigQuery production target + Terraform IaC

**Status:** Accepted
**Date:** 2026-06-19
**Phase:** 7
**Resolves:** ADR-0001 open item (prod target deferred), ADR-0011 deferral

---

## Context

ADR-0001 established the dual-target strategy: DuckDB for dev, BigQuery for
prod. The prod target was deferred because the personal GCP project did not
exist. ADR-0011 (Phase 6) reaffirmed the deferral.

Phase 7 resolves the deferral by:

1. Defining the BigQuery `prod` target in `profiles.yml` with env-var-based
   auth (no credentials in the repo).
2. Writing Terraform IaC to provision the BigQuery datasets.
3. Adding a GitHub Actions workflow for scheduled dbt runs against BigQuery.

The GCP project itself (BigQuery Sandbox, personal Google account) is a
manual one-time setup. Terraform manages the datasets and IAM bindings
inside the project.

---

## Decision

### profiles.yml: `prod` target

A `prod` output is added to the `credit_platform` profile:

```yaml
prod:
  type: bigquery
  method: "{{ 'service-account' if env_var('BQ_KEYFILE', '') != '' else 'oauth' }}"
  project: "{{ env_var('BQ_PROJECT_ID') }}"
  keyfile: "{{ env_var('BQ_KEYFILE', '') }}"
  dataset: dwh
  location: EU
  threads: 4
  timeout_seconds: 300
```

- Auth prefers ADC (oauth) for local dev; falls back to a service-account
  keyfile for CI.
- `BQ_PROJECT_ID` and `BQ_KEYFILE` are env vars — never committed.
- `dataset: dwh` is the default dataset; per-model schema overrides in
  `dbt_project.yml` (`stg`, `int`, `dwh`, `mart_risk`, `mart_finance`,
  `elementary`) control which dataset each model lands in.

### Terraform IaC (`terraform/`)

A single `main.tf` provisions 6 BigQuery datasets (`stg`, `int`, `dwh`,
`mart_risk`, `mart_finance`, `elementary`) in the GCP project, with optional
IAM bindings for a dbt service account. Terraform state is local (no remote
backend — this is a personal project, not a team).

### GitHub Actions: `dbt-prod.yml`

A `workflow_dispatch` + (commented) daily cron workflow that:

1. Generates the synthetic landing zone
2. Runs `dbt build --target prod` against BigQuery
3. Uses `BQ_PROJECT_ID` and `BQ_KEYFILE_JSON` repository secrets

The schedule is commented out until the GCP project is provisioned and secrets
are configured.

### Manual setup steps (not automated)

1. Create a GCP project via the Google Cloud Console (BigQuery Sandbox, free
   tier, personal Google account).
2. Run `terraform apply -var="project_id=<your-project>"` to create datasets.
3. Create a service account (optional; ADC works for manual runs).
4. Add `BQ_PROJECT_ID` and `BQ_KEYFILE_JSON` as GitHub Actions secrets.
5. Uncomment the cron schedule in `.github/workflows/dbt-prod.yml`.

---

## Alternatives considered

**Remote Terraform backend (GCS).** Overkill for a single-contributor
personal project. Local state is sufficient; if the project grows to multiple
contributors, a remote backend is a one-line change.

**Workload Identity Federation instead of keyfile.** The gold standard for GCP
CI auth — eliminates long-lived credentials. Deferred because it requires
configuring a Workload Identity Pool in the GCP project first, which is a
manual step that depends on the project existing. The workflow is structured
so swapping to WIF is a drop-in change (replace the keyfile step with the
`google-github-actions/auth` action).

**Skip Terraform; create datasets manually.** Works once, but is not
reproducible, not reviewable, and not the signal a staff-level portfolio
project should send. Terraform is 80 lines and provisions the entire dataset
layer declaratively.

**BigQuery Emulator for CI.** No mature emulator exists that supports
`dbt-bigquery`'s DDL and DML patterns. The DuckDB dev target already provides
CI coverage; BigQuery is the production deployment story.

---

## Consequences

**Resolved:**

- The ADR-0001 open item ("choose the Google account + billing account") is
  resolved in principle: the `prod` target and Terraform are ready; the
  manual GCP project creation is the only remaining step.
- ADR-0011's "BigQuery + Terraform IaC still deferred" is no longer deferred.

**New constraint:**

- All model SQL must remain portable across DuckDB and BigQuery. This was
  already an accepted constraint from ADR-0001; it is now enforced by having
  a real BQ target that will be tested.
- The `dbt-bigquery` adapter is a main dependency (not dev-only), because the
  prod target is the production deployment path.

**Not changed:**

- CI (`make ci`) still runs against DuckDB. The BQ workflow is a separate
  deployment workflow, not a PR gate.
- The DuckDB dev target remains the default.
