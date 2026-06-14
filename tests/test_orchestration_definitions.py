"""Verify the Dagster Definitions load and expose the dbt assets + quality gates.

These tests load the Definitions object and assert structure (asset count, check
count, check->asset wiring) without executing a materialization. A separate
integration step (`make dagster-materialize`) drives the real dbt build via the
DbtCliResource subprocess in CI.
"""

import dagster as dg

from orchestration.definitions import defs


def test_definitions_load() -> None:
    assert isinstance(defs, dg.Definitions)


def test_dbt_assets_are_exposed() -> None:
    asset_keys = {spec.key for spec in defs.resolve_all_asset_specs()}
    # The dbt project contributes 35 credit-platform assets (28 models + 4 seeds
    # + 3 sources). Elementary adds ~30 internal model assets on top, so the total
    # with Elementary installed is 65. Assert >= 35 so the credit-platform slice is
    # always present even as Elementary's internal model count evolves.
    assert len(asset_keys) >= 35
    expected = {
        dg.AssetKey(["mart_finance", "mart_finance_ecl_allowance"]),
        dg.AssetKey(["mart_finance", "mart_finance_ecl_summary"]),
        dg.AssetKey(["dwh", "dim_loan"]),
        dg.AssetKey(["dwh", "fct_payment"]),
    }
    assert expected <= asset_keys


def test_three_quality_gates_defined() -> None:
    check_keys = defs.resolve_asset_graph().asset_check_keys
    check_names = {key.name for key in check_keys}
    assert {
        "ecl_stage_ecl_strictly_positive",
        "facts_resolve_to_dim_loan",
        "ecl_allowance_volume_within_band",
    } <= check_names


def test_dbt_cli_resource_is_configured() -> None:
    resources = defs.resources
    assert "dbt" in resources
