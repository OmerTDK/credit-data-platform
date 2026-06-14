with pd_coverage as (
    select
        int_ecl_pd_term_structure.product_type,
        int_ecl_pd_term_structure.score_band,
        int_ecl_pd_term_structure.pd_lifetime as current_bucket_lifetime_pd
    from {{ ref('int_ecl_pd_term_structure') }} as int_ecl_pd_term_structure
    where int_ecl_pd_term_structure.starting_bucket = 'current'
)

select
    int_ecl_staging.loan_id,
    int_ecl_staging.current_loan_status,
    int_ecl_staging.product_type,
    int_ecl_staging.score_band,
    int_ecl_staging.origination_pd_rate
from {{ ref('int_ecl_staging') }} as int_ecl_staging
inner join pd_coverage
    on
        int_ecl_staging.product_type = pd_coverage.product_type
        and int_ecl_staging.score_band = pd_coverage.score_band
where
    not int_ecl_staging.is_terminal
    and pd_coverage.current_bucket_lifetime_pd > 0.0
    and (
        int_ecl_staging.origination_pd_rate is null
        or int_ecl_staging.origination_pd_rate = 0.0
    )
