# ADR-0001: Dual-target warehouse — DuckDB for dev, BigQuery for prod

**Date:** 2026-06-10
**Status:** Accepted

## Context

The platform's dbt project needs a warehouse from day one. Two forces pull in
opposite directions:

- Development and CI need fast, free, credential-less feedback. Every PR must
  validate that the dbt project compiles, and later phases must run the full
  pipeline locally without a cloud account.
- The brief's definition of "deployed" is scheduled dbt runs against a real
  cloud warehouse (BigQuery) plus a published docs site. A local-only warehouse
  never demonstrates production behavior: datasets, partitioning, cost.

A related question is where dbt connection config lives: the conventional
`~/.dbt/profiles.yml` is per-machine hidden state, which fights
reproducibility for a public repo.

## Decision

Two dbt targets under one profile (`credit_platform`):

- **`dev` (default): DuckDB**, a local file at `data/local/credit_platform.duckdb`
  (gitignored). Used by local development, `make dbt-*`, pytest, and CI.
- **`prod`: BigQuery — deferred.** The target is not defined yet because the
  personal GCP project does not exist: which Google account and billing
  account host it is an open decision. When it lands, the target uses
  `env_var()` for project/dataset/keyfile so no credential ever enters the
  repo, and `dbt-bigquery` joins the main dependencies.

`profiles.yml` is committed at the repo root and consumed via
`DBT_PROFILES_DIR=.` (Makefile, CI, and the pytest parse gate all set it).
The dev profile contains zero secrets — a relative file path and a thread
count — so committing it trades nothing away and buys clone-and-run
reproducibility.

Dependency placement: `dbt-core` is a main dependency (the transform engine is
the product), `dbt-duckdb` is a dev-group dependency (the dev-only adapter;
the prod adapter will be a main dependency). Python is pinned to 3.13
(`requires-python = ">=3.12,<3.14"`) because `dbt-core` 1.11 crashes on import
under Python 3.14 (mashumaro serialization error), despite its metadata
claiming `>=3.10`.

## Alternatives considered

- **BigQuery-only.** Every contributor and every CI run needs GCP credentials
  and a billing account; PR feedback is slower and costs money; the repo stops
  being clone-and-run for reviewers. Lost on friction and cost.
- **DuckDB-only.** No production deployment story — the brief explicitly
  requires scheduled runs against BigQuery, and supporting both engines is
  itself the portability signal this project wants to send. Lost on scope.
- **Postgres for dev.** Requires a running server, adds container management
  to every workflow, and is row-oriented — worse OLAP parity with BigQuery
  than DuckDB's columnar engine. DuckDB is the established local-analytics
  default for dbt. Lost on setup weight.
- **Profiles in `~/.dbt/` (dbt default).** Hidden per-machine state; every
  contributor reconstructs it by hand; CI needs a separate copy that can
  drift. Committing a secret-free profile is strictly better here. Lost on
  reproducibility.
- **Inventing the BigQuery target now with placeholder credentials.** A
  committed-but-broken target fails loudly for anyone who tries it and rots
  silently otherwise. Deferring keeps `profiles.yml` honest: everything in it
  works. Lost on honesty.

## Consequences

- CI validates the dbt project (`dbt parse`) and lints SQL (SQLFluff, duckdb
  dialect, dbt templater) on every PR with no secrets configured.
- All model SQL must stay portable across DuckDB and BigQuery — dialect
  divergences get handled via dbt macros/`adapter.dispatch`, not forks of
  model code. This is a real constraint accepted deliberately.
- A two-target test story (run the same models against both engines) becomes
  possible and is expected once the prod target lands.
- Open item: choose the Google account + billing account for the personal GCP
  project, then add the `prod` target and `dbt-bigquery`.
