with loans as (
    select
        loan_id,
        borrower_id
    from {{ ref('int_loan') }}
),

perf as (
    select
        loan_id,
        report_month,
        delinquency_bucket
    from {{ ref('int_monthly_performance') }}
),

borrower_monthly as (
    select
        loans.borrower_id,
        perf.report_month,
        perf.delinquency_bucket
    from loans
    inner join perf on loans.loan_id = perf.loan_id
),

severity_ranked as (
    select
        borrower_id,
        report_month,
        max(
            case delinquency_bucket
                when 'current' then 1
                when 'dpd_30' then 2
                when 'dpd_60' then 3
                when 'dpd_90_plus' then 4
                when 'default' then 5
                else 0
            end
        ) as worst_severity
    from borrower_monthly
    group by borrower_id, report_month
),

bucket_mapped as (
    select
        borrower_id,
        report_month,
        case worst_severity
            when 5 then 'default'
            when 4 then 'dpd_90_plus'
            when 3 then 'dpd_60'
            when 2 then 'dpd_30'
            else 'current'
        end as current_delinquency_bucket
    from severity_ranked
)

select
    borrower_id,
    report_month,
    current_delinquency_bucket
from bucket_mapped
