{{ config(alias='loanbook__borrower') }}

select
    borrower_id,
    age_band,
    income_band,
    region,
    score_band,
    cast(credit_score as integer) as credit_score
from {{ source('loanbook', 'borrowers') }}
