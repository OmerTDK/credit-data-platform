---
title: Vintage Curves
---

Cumulative loss and prepayment behaviour by origination cohort and months on
book (MOB). These curves implement the same arithmetic as the `vintage_loss_curve`
and `cpr` semantic metrics, but read from the mart tables directly
(`mart_risk.mart_risk_vintage_curve` and `mart_risk.mart_risk_prepayment_speed`)
rather than via the MetricFlow API — the two paths are kept in agreement by the
pinned semantic tests in `tests/test_semantic_layer.py`.

```sql vintage_curve
select * from credit_platform.vintage_curve
```

```sql products
select distinct product_type from credit_platform.vintage_curve order by product_type
```

<Dropdown data={products} name=product value=product_type defaultValue="auto_loan"/>

## Cumulative default rate by cohort

```sql vintage_for_product
select *
from credit_platform.vintage_curve
where product_type = '${inputs.product.value}'
```

<LineChart
    data={vintage_for_product}
    x=months_on_book
    y=vintage_loss_curve
    series=cohort_quarter
    yFmt=pct1
    yAxisTitle="Cumulative default rate"
    xAxisTitle="Months on book"
    title="Vintage loss curve — {inputs.product.value}"
/>

## Prepayment speed (annualized CPR)

```sql prepayment_speed
select * from credit_platform.prepayment_speed
```

```sql prepay_for_product
select *
from credit_platform.prepayment_speed
where product_type = '${inputs.product.value}'
```

<LineChart
    data={prepay_for_product}
    x=months_on_book
    y=cpr_rate
    series=cohort_quarter
    yFmt=pct1
    yAxisTitle="CPR"
    xAxisTitle="Months on book"
    title="Conditional prepayment rate — {inputs.product.value}"
/>
