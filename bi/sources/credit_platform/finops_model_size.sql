-- FinOps / cost-attribution proxy. DuckDB has no per-query billing, so the
-- materialized-warehouse footprint is the proxy: rows x columns ("cells") is a
-- size-and-scan signal that tracks how much a model would cost to store and
-- scan on a real warehouse (BigQuery bytes-scanned, Snowflake credits). Layer =
-- schema (dwh / mart_risk / mart_finance / ...).
select
    schema_name as layer,
    table_name as model,
    estimated_size as row_count,
    column_count,
    estimated_size * column_count as cell_count
from duckdb_tables()
where schema_name in ('dwh', 'mart_risk', 'mart_finance')
order by cell_count desc
