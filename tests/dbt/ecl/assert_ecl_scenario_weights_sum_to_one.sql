with scenario_weights as (
    select
        scenario_name,
        scenario_weight
    from {{ ref('ecl_scenario_weights') }}
    where scenario_name != 'probability_weighted'
)

select sum(scenario_weight) as total_weight
from scenario_weights
having abs(sum(scenario_weight) - 1.0) > 0.0001
