{{ config(materialized='table') }}

with product_definitions as (
    select
        'personal_loan' as product_type,
        'Personal Loan' as product_name,
        'installment' as product_family,
        true as is_amortizing,
        false as is_revolving
    union all
    select
        'auto_loan' as product_type,
        'Auto Loan' as product_name,
        'installment' as product_family,
        true as is_amortizing,
        false as is_revolving
    union all
    select
        'mortgage' as product_type,
        'Mortgage' as product_name,
        'installment' as product_family,
        true as is_amortizing,
        false as is_revolving
    union all
    select
        'credit_card' as product_type,
        'Credit Card' as product_name,
        'revolving' as product_family,
        false as is_amortizing,
        true as is_revolving
)

select
    {{ generate_surrogate_key(['product_type']) }} as product_key,
    product_type,
    product_name,
    product_family,
    is_amortizing,
    is_revolving
from product_definitions
