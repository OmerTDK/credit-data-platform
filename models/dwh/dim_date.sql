{{ config(materialized='table') }}

with date_range as (
    select
        cast('2020-01-01' as date) as start_date,
        cast('2030-01-01' as date) as end_date
),

numbers as (
    select unnest(range(0, 3653)) as n
),

date_spine as (
    select date_range.start_date + interval (numbers.n) day as full_date
    from date_range
    cross join numbers
    where date_range.start_date + interval (numbers.n) day < date_range.end_date
),

date_attributes as (
    select
        cast(strftime(full_date, '%Y%m%d') as integer) as date_key,
        cast(full_date as date) as full_date,
        cast(extract(isodow from full_date) as integer) as day_of_week,
        cast(extract(day from full_date) as integer) as day_of_month,
        cast(extract(doy from full_date) as integer) as day_of_year,
        cast(extract(week from full_date) as integer) as week_of_year,
        cast(extract(month from full_date) as integer) as month_number,
        cast(extract(quarter from full_date) as integer) as quarter_number,
        cast(extract(year from full_date) as integer) as year_number,
        cast(extract(year from full_date) as integer) as fiscal_year,
        cast(extract(quarter from full_date) as integer) as fiscal_quarter,
        strftime(full_date, '%A') as day_name,
        strftime(full_date, '%B') as month_name,
        extract(isodow from full_date) in (6, 7) as is_weekend
    from date_spine
)

select
    date_key,
    full_date,
    day_of_week,
    day_name,
    day_of_month,
    day_of_year,
    week_of_year,
    month_number,
    month_name,
    quarter_number,
    year_number,
    is_weekend,
    fiscal_year,
    fiscal_quarter
from date_attributes
