{{ config(materialized='table') }}

with borrowers as (
    select
        borrower_id,
        age_band,
        income_band,
        region,
        score_band,
        credit_score
    from {{ ref('int_borrower') }}
),

monthly_delinquency as (
    select
        borrower_id,
        report_month,
        current_delinquency_bucket
    from {{ ref('int_borrower_monthly_delinquency') }}
),

first_month as (
    select
        borrower_id,
        min(report_month) as origination_report_month
    from monthly_delinquency
    group by borrower_id
),

borrowers_with_baseline as (
    select
        borrowers.borrower_id,
        borrowers.age_band,
        borrowers.income_band,
        borrowers.region,
        borrowers.score_band,
        borrowers.credit_score,
        coalesce(fm.origination_report_month, cast('2020-01-01' as date)) as first_active_month
    from borrowers
    left join first_month as fm on borrowers.borrower_id = fm.borrower_id
),

all_months as (
    select
        borrowers_with_baseline.borrower_id,
        borrowers_with_baseline.age_band,
        borrowers_with_baseline.income_band,
        borrowers_with_baseline.region,
        borrowers_with_baseline.score_band,
        borrowers_with_baseline.credit_score,
        monthly_delinquency.report_month,
        monthly_delinquency.current_delinquency_bucket
    from borrowers_with_baseline
    left join monthly_delinquency
        on borrowers_with_baseline.borrower_id = monthly_delinquency.borrower_id
),

change_detection as (
    select
        borrower_id,
        age_band,
        income_band,
        region,
        score_band,
        credit_score,
        report_month,
        current_delinquency_bucket,
        lag(current_delinquency_bucket) over (
            partition by borrower_id
            order by report_month
        ) as prev_delinquency_bucket
    from all_months
),

version_markers as (
    select
        borrower_id,
        age_band,
        income_band,
        region,
        score_band,
        credit_score,
        report_month,
        current_delinquency_bucket,
        case
            when
                prev_delinquency_bucket is null
                or prev_delinquency_bucket != current_delinquency_bucket
                then 1
            else 0
        end as is_new_version
    from change_detection
),

version_numbers as (
    select
        borrower_id,
        age_band,
        income_band,
        region,
        score_band,
        credit_score,
        report_month,
        current_delinquency_bucket,
        sum(is_new_version) over (
            partition by borrower_id
            order by report_month
            rows between unbounded preceding and current row
        ) as version_number
    from version_markers
),

scd2_windows as (
    select
        borrower_id,
        age_band,
        income_band,
        region,
        score_band,
        credit_score,
        current_delinquency_bucket,
        version_number,
        min(report_month) as _valid_from,
        max(report_month) as last_active_month
    from version_numbers
    group by
        borrower_id,
        age_band,
        income_band,
        region,
        score_band,
        credit_score,
        current_delinquency_bucket,
        version_number
),

scd2_final as (
    select
        borrower_id,
        age_band,
        income_band,
        region,
        score_band,
        credit_score,
        current_delinquency_bucket,
        version_number,
        _valid_from,
        coalesce(
            lead(_valid_from) over (partition by borrower_id order by _valid_from),
            cast('9999-12-31' as date)
        ) as _valid_to,
        lead(_valid_from) over (partition by borrower_id order by _valid_from) is null
            as _is_current
    from scd2_windows
)

select
    {{ generate_surrogate_key(['borrower_id', 'version_number']) }} as borrower_version_key,
    {{ generate_surrogate_key(['borrower_id']) }}                    as borrower_key,
    borrower_id,
    age_band,
    income_band,
    region,
    score_band,
    credit_score,
    current_delinquency_bucket,
    cast(version_number as integer) as version_number,
    _valid_from,
    _valid_to,
    _is_current,
    current_timestamp as _loaded_at
from scd2_final
