-- Mart-prep intermediate. Reads DWH facts/dimensions and risk marts to build
-- ECL-specific base LGD per loan for downstream mart_finance_ecl_* marts.

{{ config(materialized='view') }}

with lgd_params as (
    select
        ecl_lgd_parameters.product_type,
        ecl_lgd_parameters.lgd_rate
    from {{ ref('ecl_lgd_parameters') }} as ecl_lgd_parameters
),

loan_products as (
    select
        dim_loan.loan_id,
        dim_loan.product_type
    from {{ ref('dim_loan') }} as dim_loan
)

select
    loan_products.loan_id,
    loan_products.product_type,
    cast(lgd_params.lgd_rate as decimal(10, 8)) as base_lgd_rate
from loan_products
inner join lgd_params
    on loan_products.product_type = lgd_params.product_type
