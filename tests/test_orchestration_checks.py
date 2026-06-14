"""Unit tests for the Dagster asset-check logic (pure functions over DuckDB).

These tests exercise the quality-gate logic directly against the built DuckDB
warehouse, decoupled from a full Dagster materialization run. The same functions
back the @asset_check definitions in src/orchestration/definitions.py.

The kill-test (test_stage_ecl_positive_catches_zeroed_stage1) proves the gate
actually fires: it points the check at a mutated copy of the summary mart where
Stage 1 ECL has been driven to zero — the regression the IFRS 9 gate must catch.
"""

import os
import shutil
import subprocess
from pathlib import Path

import duckdb
import pytest

from orchestration.checks import (
    CheckOutcome,
    check_ecl_stage_ecl_positive,
    check_referential_integrity_facts_to_dims,
    check_volume_sanity_ecl_allowance,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DUCKDB_FILE = REPO_ROOT / "data" / "local" / "credit_platform.duckdb"


@pytest.fixture(scope="module")
def warehouse() -> Path:
    """Build the full (non-Elementary) project so the warehouse exists for the checks.

    Building everything except `tag:elementary` makes this fixture completely
    self-sufficient and order-independent: the conformed dims referenced by the
    DWH relationship tests (dim_date, dim_product) are always present, so the
    checks never silently skip or fail on a partial build in CI. Elementary tests
    are excluded because their model layer is built only in the full Dagster
    materialization (see test_orchestration_materialize.py).
    """
    DUCKDB_FILE.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["uv", "run", "dbt", "build", "--exclude", "tag:elementary"],
        cwd=REPO_ROOT,
        env={**os.environ, "DBT_PROFILES_DIR": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"warehouse build failed (exit {completed.returncode}):\n{completed.stdout}"
    )
    return DUCKDB_FILE


def test_stage_ecl_positive_passes_on_real_book(warehouse: Path) -> None:
    outcome = check_ecl_stage_ecl_positive(warehouse)
    assert outcome.passed, outcome.metadata
    assert outcome.metadata["min_stage1_ecl"] > 0
    assert outcome.metadata["min_stage2_ecl"] > 0


def test_referential_integrity_passes_on_real_book(warehouse: Path) -> None:
    outcome = check_referential_integrity_facts_to_dims(warehouse)
    assert outcome.passed, outcome.metadata
    assert outcome.metadata["orphan_rows_total"] == 0


def test_volume_sanity_passes_on_real_book(warehouse: Path) -> None:
    outcome = check_volume_sanity_ecl_allowance(warehouse)
    assert outcome.passed, outcome.metadata
    assert outcome.metadata["row_count"] > 0


def test_stage_ecl_positive_catches_zeroed_stage1(warehouse: Path, tmp_path: Path) -> None:
    """Kill-test: a portfolio whose Stage 1 ECL collapses to zero must FAIL the gate.

    This is the regression the IFRS 9 gate exposed — if a PD term-structure change
    drives all Stage 1 PDs to zero, the performing book would carry no loss
    allowance. We mutate a copy of the summary mart and confirm the gate fires.
    """
    mutated = tmp_path / "mutated.duckdb"
    shutil.copy(warehouse, mutated)
    with duckdb.connect(str(mutated)) as connection:
        connection.execute(
            "UPDATE mart_finance.mart_finance_ecl_summary "
            "SET total_ecl_amount = 0 WHERE ifrs9_stage = 1"
        )

    outcome = check_ecl_stage_ecl_positive(mutated)
    assert not outcome.passed
    assert outcome.metadata["min_stage1_ecl"] == 0
    assert isinstance(outcome, CheckOutcome)


def test_referential_integrity_catches_orphan_fact(warehouse: Path, tmp_path: Path) -> None:
    """Kill-test: an orphan fact row (loan_id not in dim_loan) must FAIL the gate."""
    mutated = tmp_path / "orphan.duckdb"
    shutil.copy(warehouse, mutated)
    with duckdb.connect(str(mutated)) as connection:
        connection.execute(
            "DELETE FROM dwh.dim_loan WHERE loan_id = (SELECT MIN(loan_id) FROM dwh.dim_loan)"
        )

    outcome = check_referential_integrity_facts_to_dims(mutated)
    assert not outcome.passed
    assert outcome.metadata["orphan_rows_total"] > 0
