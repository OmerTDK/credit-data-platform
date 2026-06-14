"""End-to-end test of the Dagster materialization path.

Executes the implicit global asset job in-process: Dagster materializes every
dbt asset by running `dbt build` through DbtCliResource (subprocess), then runs
all asset checks (the three custom gates plus every dbt schema test, surfaced as
checks by dagster-dbt). Asserts the run succeeds and the three custom gates pass.

This is the heaviest test in the suite (full dbt build) so it lives in its own
file; `make ci` runs it via the standard `uv run pytest` invocation.
"""

from orchestration.materialize import materialize_all

CUSTOM_GATE_NAMES = {
    "ecl_stage_ecl_strictly_positive",
    "facts_resolve_to_dim_loan",
    "ecl_allowance_volume_within_band",
}


def test_materialization_succeeds_and_gates_pass() -> None:
    result = materialize_all(raise_on_error=False)
    assert result.success, "Dagster asset job (dbt build + checks) did not succeed"

    evaluations = {
        evaluation.check_name: evaluation for evaluation in result.get_asset_check_evaluations()
    }
    missing = CUSTOM_GATE_NAMES - evaluations.keys()
    assert not missing, f"custom gates did not run: {missing}"

    for name in CUSTOM_GATE_NAMES:
        assert evaluations[name].passed, f"gate {name} failed: {evaluations[name].metadata}"
