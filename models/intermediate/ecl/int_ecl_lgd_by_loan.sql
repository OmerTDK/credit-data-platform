-- Mart-prep intermediate. Computes base Loss Given Default (LGD) per loan.
-- Grain: one row per loan_id.
--
-- LGD is product-type driven: unsecured products have higher LGD than collateralized.
-- Base LGD comes from seeds/ecl_lgd_parameters.csv. Scenario LGD scalars are applied
-- in int_ecl_components where the scenario cross-join occurs, keeping this intermediate
-- scenario-agnostic and the LGD seed values as the single source of truth.

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
