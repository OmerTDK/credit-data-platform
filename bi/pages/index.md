---
title: Portfolio Overview
---

Headline view of the synthetic multi-product consumer-credit book. Every number
here is also defined once in the MetricFlow semantic layer (`models/semantic/`),
so this dashboard and the downstream metrics API never disagree.

```sql portfolio_kpis
select * from credit_platform.portfolio_kpis
```

<BigValue
    data={portfolio_kpis}
    value=origination_volume
    fmt=usd0
    title="Origination volume"
/>

<BigValue
    data={portfolio_kpis}
    value=loan_count
    fmt=num0
    title="Loans originated"
/>

<BigValue
    data={portfolio_kpis}
    value=default_rate
    fmt=pct1
    title="Lifetime default rate"
/>

<BigValue
    data={portfolio_kpis}
    value=avg_balance
    fmt=usd0
    title="Average balance"
/>

<BigValue
    data={portfolio_kpis}
    value=portfolio_yield
    fmt=pct2
    title="Periodic yield"
/>

<BigValue
    data={portfolio_kpis}
    value=delinquency_rate
    fmt=pct1
    title="Delinquency rate (loan-months)"
/>

## Origination by product and credit tier

```sql origination_by_product
select * from credit_platform.origination_by_product
```

<BarChart
    data={origination_by_product}
    x=product_type
    y=origination_volume
    series=credit_tier
    title="Origination volume by product and credit tier"
    yFmt=usd0
/>

<DataTable data={origination_by_product} rows=20>
    <Column id=product_type title="Product"/>
    <Column id=credit_tier title="Credit tier"/>
    <Column id=loan_count title="Loans" fmt=num0/>
    <Column id=origination_volume title="Volume" fmt=usd0/>
</DataTable>

## Pages

- [Vintage curves](/vintage-curves) — cumulative loss and prepayment by cohort.
- [Risk-cohort drill-down](/risk-cohorts) — default and prepayment by credit tier.
- [FinOps / cost](/finops) — warehouse footprint as a cost-attribution proxy.
