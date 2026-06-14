# Evidence dashboard — credit-data-platform

BI-as-code dashboard (Evidence / evidence.dev) over the dbt-built DuckDB
warehouse. Four pages: portfolio overview (`pages/index.md`), vintage curves,
risk-cohort drill-down, and a FinOps / cost view. See
[ADR-0011](../docs/adr/0011-semantic-layer-and-evidence-dashboard.md).

## Prerequisites

The warehouse must be built first — the DuckDB file at
`../data/local/credit_platform.duckdb` is the data source (see
`sources/credit_platform/connection.yaml`). From the repo root:

```bash
make generate          # synthetic loan book
make dbt-build-semantic # dwh + marts the dashboard reads
```

## Build (run from the repo root)

```bash
make evidence-install   # one-time: npm install
make evidence-build     # npm run sources && npm run build -> bi/build
```

Then open `bi/build/index.html`, or `make evidence-build && cd bi && npm run preview`.

## CI

The Node build is intentionally **not** part of `make ci` (CI is Python-only and
network-free). The query layer is covered instead by
`../tests/test_evidence_dashboard.py`, which executes every source query in
`sources/credit_platform/` against the warehouse on every PR.
