"""Materialize the dbt assets through Dagster and evaluate the quality gates.

This is the asset-materialization path wired into CI (`make dagster-materialize`).
It executes the implicit global asset job in-process: Dagster materializes every
dbt asset by running `dbt build` through DbtCliResource (a managed subprocess —
not a bare shell `dbt build`), then runs the three @asset_check gates against the
resulting DuckDB warehouse. An ERROR-severity check failure fails the run, which
fails CI.
"""

import sys

from dagster import ExecuteInProcessResult

from orchestration.definitions import defs


def materialize_all(raise_on_error: bool = False) -> ExecuteInProcessResult:
    """Run the full asset job (dbt build via DbtCliResource) plus all asset checks."""
    job = defs.get_implicit_global_asset_job_def()
    return job.execute_in_process(raise_on_error=raise_on_error)


def main() -> int:
    result = materialize_all(raise_on_error=False)
    check_evaluations = result.get_asset_check_evaluations()
    for evaluation in check_evaluations:
        status = "PASS" if evaluation.passed else "FAIL"
        print(
            f"[{status}] {evaluation.check_name} "
            f"(severity={evaluation.severity.value}) {dict(evaluation.metadata)}"
        )
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
