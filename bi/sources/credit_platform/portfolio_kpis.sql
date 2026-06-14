-- Portfolio headline KPIs. These mirror the MetricFlow semantic definitions
-- (origination_volume, default_rate, avg_balance) so the dashboard and the
-- semantic layer report the same numbers.
with originations as (
    select
        count(*) as loan_count,
        sum(principal_amount) as origination_volume
    from dwh.fct_loan_origination
),

lifecycle as (
    select avg(case when has_defaulted then 1.0 else 0.0 end) as default_rate
    from dwh.fct_loan_lifecycle
),

balances as (
    select
        avg(ending_balance_amount) as avg_balance,
        sum(interest_charged_amount) / nullif(sum(beginning_balance_amount), 0)
            as portfolio_yield,
        avg(
            case
                when delinquency_bucket in ('dpd_30', 'dpd_60', 'dpd_90_plus', 'default')
                    then 1.0
                else 0.0
            end
        ) as delinquency_rate
    from dwh.fct_payment
)

select
    originations.loan_count,
    originations.origination_volume,
    lifecycle.default_rate,
    balances.avg_balance,
    balances.portfolio_yield,
    balances.delinquency_rate
from originations
cross join lifecycle
cross join balances
