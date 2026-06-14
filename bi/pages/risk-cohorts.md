---
title: Risk-Cohort Drill-Down
---

Lifetime default and prepayment rates by credit tier and product. The default
gradient across tiers (subprime worst, super-prime best) is the same signal the
`default_rate` metric exposes when grouped by `credit_tier`.

```sql cohort_risk
select * from credit_platform.cohort_risk
```

## Default rate by credit tier

<BarChart
    data={cohort_risk}
    x=credit_tier
    y=default_rate
    series=product_type
    type=grouped
    yFmt=pct1
    yAxisTitle="Lifetime default rate"
    title="Default rate by credit tier and product"
    swapXY=true
/>

## Prepayment rate by credit tier

<BarChart
    data={cohort_risk}
    x=credit_tier
    y=prepayment_rate
    series=product_type
    type=grouped
    yFmt=pct1
    yAxisTitle="Lifetime prepayment rate"
    title="Prepayment rate by credit tier and product"
    swapXY=true
/>

## Cohort detail

<DataTable data={cohort_risk} rows=25>
    <Column id=credit_tier title="Credit tier"/>
    <Column id=product_type title="Product"/>
    <Column id=loan_count title="Loans" fmt=num0/>
    <Column id=default_rate title="Default rate" fmt=pct1 contentType=colorscale colorScale=negative/>
    <Column id=prepayment_rate title="Prepayment rate" fmt=pct1/>
</DataTable>
