"""Dagster Definitions: the dbt project as software-defined assets + quality gates.

The dbt project is exposed via @dbt_assets — every dbt model (28 of them) becomes
a Dagster asset, materialized by running `dbt build` through DbtCliResource (a
managed subprocess, never a bare shell `dbt build`). Three @asset_check gates run
against the built DuckDB warehouse:

* ecl_stage_ecl_strictly_positive (ERROR) — Stage 1/2 portfolio ECL > 0.
* facts_resolve_to_dim_loan (ERROR)       — referential integrity facts -> dims.
* ecl_allowance_volume_within_band (WARN) — row-count sanity on the ECL mart.

ERROR gates fail the run; the WARN gate surfaces a non-blocking signal.
"""

from pathlib import Path

import dagster as dg
from dagster_dbt import (
    DbtCliResource,
    DbtProject,
    dbt_assets,
    get_asset_key_for_model,
)

from orchestration.checks import (
    CheckOutcome,
    check_ecl_stage_ecl_positive,
    check_referential_integrity_facts_to_dims,
    check_volume_sanity_ecl_allowance,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "local" / "credit_platform.duckdb"

dbt_project = DbtProject(
    project_dir=PROJECT_ROOT,
    profiles_dir=PROJECT_ROOT,
    target="dev",
)
dbt_project.prepare_if_dev()

dbt_resource = DbtCliResource(project_dir=dbt_project)


@dbt_assets(manifest=dbt_project.manifest_path)
def credit_platform_dbt_assets(context: dg.AssetExecutionContext, dbt: DbtCliResource) -> None:
    yield from dbt.cli(["build"], context=context).stream()


def _to_check_result(outcome: CheckOutcome, severity: dg.AssetCheckSeverity) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=outcome.passed,
        severity=severity,
        metadata=outcome.metadata,
    )


@dg.asset_check(
    asset=get_asset_key_for_model([credit_platform_dbt_assets], "mart_finance_ecl_summary"),
    name="ecl_stage_ecl_strictly_positive",
    description="Stage 1 and Stage 2 portfolio ECL must be strictly positive in every scenario.",
    blocking=True,
)
def ecl_stage_ecl_strictly_positive() -> dg.AssetCheckResult:
    outcome = check_ecl_stage_ecl_positive(WAREHOUSE_PATH)
    return _to_check_result(outcome, dg.AssetCheckSeverity.ERROR)


@dg.asset_check(
    asset=get_asset_key_for_model([credit_platform_dbt_assets], "mart_finance_ecl_allowance"),
    name="facts_resolve_to_dim_loan",
    description="Every fact/mart loan_id must resolve to a dim_loan row.",
    blocking=True,
)
def facts_resolve_to_dim_loan() -> dg.AssetCheckResult:
    outcome = check_referential_integrity_facts_to_dims(WAREHOUSE_PATH)
    return _to_check_result(outcome, dg.AssetCheckSeverity.ERROR)


@dg.asset_check(
    asset=get_asset_key_for_model([credit_platform_dbt_assets], "mart_finance_ecl_allowance"),
    name="ecl_allowance_volume_within_band",
    description="ECL allowance row count must sit within the expected volume band.",
)
def ecl_allowance_volume_within_band() -> dg.AssetCheckResult:
    outcome = check_volume_sanity_ecl_allowance(WAREHOUSE_PATH)
    return _to_check_result(outcome, dg.AssetCheckSeverity.WARN)


defs = dg.Definitions(
    assets=[credit_platform_dbt_assets],
    asset_checks=[
        ecl_stage_ecl_strictly_positive,
        facts_resolve_to_dim_loan,
        ecl_allowance_volume_within_band,
    ],
    resources={"dbt": dbt_resource},
)
