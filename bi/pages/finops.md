---
title: FinOps / Cost
---

Cost-attribution proxy for the warehouse. DuckDB has no per-query billing, so the
materialized footprint stands in: **cells = rows x columns** tracks how much each
model would cost to store and scan on a metered warehouse (BigQuery bytes
scanned, Snowflake credits). When the BigQuery prod target lands (see
`docs/adr/0011`), this view swaps to `INFORMATION_SCHEMA.JOBS` real spend.

```sql finops_model_size
select * from credit_platform.finops_model_size
```

```sql finops_by_layer
select
    layer,
    sum(row_count) as rows,
    sum(cell_count) as cells
from credit_platform.finops_model_size
group by layer
order by cells desc
```

<BigValue
    data={finops_by_layer}
    value=cells
    fmt=num0
    title="Total warehouse cells (dwh + marts)"
/>

## Footprint by layer

<BarChart
    data={finops_by_layer}
    x=layer
    y=cells
    title="Cost proxy (cells) by layer"
    yFmt=num0
/>

## Cost proxy by model

<BarChart
    data={finops_model_size}
    x=model
    y=cell_count
    series=layer
    title="Cost proxy (cells) by model"
    yFmt=num0
    swapXY=true
/>

<DataTable data={finops_model_size} rows=25>
    <Column id=layer title="Layer"/>
    <Column id=model title="Model"/>
    <Column id=row_count title="Rows" fmt=num0/>
    <Column id=column_count title="Columns" fmt=num0/>
    <Column id=cell_count title="Cells (cost proxy)" fmt=num0 contentType=colorscale colorScale=info/>
</DataTable>
