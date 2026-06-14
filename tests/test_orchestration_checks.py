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


def test_stage_ecl_positive_catches_zeroed_stage2(warehouse: Path, tmp_path: Path) -> None:
    """Kill-test: a portfolio whose Stage 2 ECL collapses to zero must FAIL the gate.

    Kills the mutant `passed = stage1_min > 0` (Stage 2 branch removed) and the
    mutant `filter (where ifrs9_stage = 2)` -> `filter (where ifrs9_stage = 3)`.
    Stage 1 ECL is left intact so stage1_min > 0, proving the two filter columns
    are independently measuring different stages.
    """
    mutated = tmp_path / "mutated_stage2.duckdb"
    shutil.copy(warehouse, mutated)
    with duckdb.connect(str(mutated)) as connection:
        connection.execute(
            "UPDATE mart_finance.mart_finance_ecl_summary "
            "SET total_ecl_amount = 0 WHERE ifrs9_stage = 2"
        )

    outcome = check_ecl_stage_ecl_positive(mutated)
    assert not outcome.passed
    assert outcome.metadata["min_stage2_ecl"] == 0
    assert outcome.metadata["min_stage1_ecl"] > 0  # Stage 1 unaffected


def test_referential_integrity_catches_orphan_fact(warehouse: Path, tmp_path: Path) -> None:
    """Kill-test: an orphan fact row (loan_id not in dim_loan) must FAIL the gate.

    Deleting one dim_loan row creates orphans in all five loan-grained relations
    simultaneously. The per-relation breakdown in metadata proves each relation is
    individually wired — a mutant silently dropping any one relation from
    LOAN_FACT_RELATIONS would leave that relation's count at 0, which this test
    would catch.
    """
    mutated = tmp_path / "orphan.duckdb"
    shutil.copy(warehouse, mutated)
    with duckdb.connect(str(mutated)) as connection:
        connection.execute(
            "DELETE FROM dwh.dim_loan WHERE loan_id = (SELECT MIN(loan_id) FROM dwh.dim_loan)"
        )

    outcome = check_referential_integrity_facts_to_dims(mutated)
    assert not outcome.passed
    assert outcome.metadata["orphan_rows_total"] > 0
    # Each relation must independently report orphans — proves no relation was silently dropped.
    assert outcome.metadata["orphans_by_relation"]["fct_payment"] > 0
    assert outcome.metadata["orphans_by_relation"]["fct_loan_state_event"] > 0
    assert outcome.metadata["orphans_by_relation"]["fct_loan_lifecycle"] > 0
    assert outcome.metadata["orphans_by_relation"]["fct_loan_origination"] > 0
    assert outcome.metadata["orphans_by_relation"]["mart_finance_ecl_allowance"] > 0


def test_volume_sanity_catches_empty_mart(warehouse: Path, tmp_path: Path) -> None:
    """Kill-test: an empty ECL allowance mart must FAIL the volume gate.

    Kills the mutant `passed = row_count <= ECL_ALLOWANCE_MAX_ROWS` (lower-bound
    removed). An empty mart has 0 rows which is below ECL_ALLOWANCE_MIN_ROWS;
    the gate must fire.
    """
    mutated = tmp_path / "empty_mart.duckdb"
    shutil.copy(warehouse, mutated)
    with duckdb.connect(str(mutated)) as connection:
        connection.execute("DELETE FROM mart_finance.mart_finance_ecl_allowance")

    outcome = check_volume_sanity_ecl_allowance(mutated)
    assert not outcome.passed
    assert outcome.metadata["row_count"] == 0
