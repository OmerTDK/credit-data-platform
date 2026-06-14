{{ config(materialized='table') }}

with days as (
    {{ dbt.date_spine('day', "make_date(2018, 1, 1)", "make_date(2026, 1, 1)") }}
)

select cast(date_day as date) as date_day
from days
