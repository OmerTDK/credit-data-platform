with borrowers as (
    select
        borrower_id,
        age_band,
        income_band,
        region,
        score_band,
        credit_score
    from {{ ref('stg_loanbook__borrower') }}
)

select
    borrower_id,
    age_band,
    income_band,
    region,
    score_band,
    credit_score
from borrowers
