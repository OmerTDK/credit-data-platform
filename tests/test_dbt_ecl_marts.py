"""Verify the ECL mart layer builds from the DWH and risk marts into mart_finance tables.

TDD: This test file defines the contracts for Phase 4 ECL marts. Run
`make ci` after implementing the mart models to verify all assertions pass.
"""

import os
import subprocess
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DUCKDB_FILE = REPO_ROOT / "data" / "local" / "credit_platform.duckdb"

EXPECTED_MART_FINANCE_TABLES = {
    ("mart_finance", "mart_finance_ecl_allowance"),
    ("mart_finance", "mart_finance_ecl_summary"),
}

EXPECTED_SCENARIOS = {"baseline", "adverse", "upside", "probability_weighted"}
VALID_STAGES = {1, 2, 3}


def _run_in_repo(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env={**os.environ, "DBT_PROFILES_DIR": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def ecl_mart_build() -> subprocess.CompletedProcess[str]:
    """Build seeds and ECL pipeline through mart_finance."""
    return _run_in_repo(
        [
            "uv",
            "run",
            "dbt",
            "build",
            "--select",
            "ecl_lgd_parameters ecl_ead_parameters ecl_scenario_weights ecl_watchlist "
            "int_ecl_pd_term_structure int_ecl_staging int_ecl_ead_by_loan "
            "int_ecl_lgd_by_loan int_ecl_components "
            "mart_finance_ecl_allowance mart_finance_ecl_summary",
        ]
    )


def test_ecl_mart_build_succeeds(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, (
        f"dbt build for ECL marts failed (exit {ecl_mart_build.returncode}):\n"
        f"stdout:\n{ecl_mart_build.stdout}\n"
        f"stderr:\n{ecl_mart_build.stderr}"
    )


def test_ecl_mart_tables_land_in_mart_finance_schema(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        tables = set(
            connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = 'mart_finance' AND table_type = 'BASE TABLE'"
            ).fetchall()
        )
    assert tables >= EXPECTED_MART_FINANCE_TABLES, (
        f"Missing mart_finance tables: {EXPECTED_MART_FINANCE_TABLES - tables}; found: {tables}"
    )


def test_ecl_allowance_has_rows(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM mart_finance.mart_finance_ecl_allowance"
        ).fetchone()[0]
    assert row_count > 0, "mart_finance_ecl_allowance is empty"


def test_ecl_allowance_all_four_scenarios_present(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        scenarios = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT scenario_name FROM mart_finance.mart_finance_ecl_allowance"
            ).fetchall()
        }
    assert scenarios == EXPECTED_SCENARIOS, (
        f"Expected 4 scenarios in allowance mart, got: {scenarios}"
    )


def test_ecl_allowance_all_stages_present(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        stages = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT ifrs9_stage FROM mart_finance.mart_finance_ecl_allowance"
            ).fetchall()
        }
    assert stages <= VALID_STAGES, f"Invalid stages found: {stages - VALID_STAGES}"
    assert len(stages) >= 1, "No stages present in allowance mart"


def test_ecl_allowance_no_negative_ecl(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_finance.mart_finance_ecl_allowance WHERE ecl_amount < 0"
        ).fetchone()[0]
    assert violations == 0, f"Found {violations} rows with negative ecl_amount"


def test_ecl_allowance_ecl_lte_ead(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_finance.mart_finance_ecl_allowance"
            " WHERE ecl_amount > ead_amount"
            "   AND scenario_name != 'probability_weighted'"
        ).fetchone()[0]
    assert violations == 0, f"Found {violations} rows where ecl_amount > ead_amount"


def test_ecl_allowance_stage3_pd_equals_one(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_finance.mart_finance_ecl_allowance"
            " WHERE ifrs9_stage = 3"
            "   AND scenario_name != 'probability_weighted'"
            "   AND ABS(pd_rate - 1.0) > 0.0001"
        ).fetchone()[0]
    assert violations == 0, f"Found {violations} Stage 3 rows where pd_rate != 1.0"


def test_ecl_allowance_stage1_uses_12m_pd(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_finance.mart_finance_ecl_allowance"
            " WHERE ifrs9_stage = 1"
            "   AND scenario_name != 'probability_weighted'"
            "   AND pd_horizon = 'lifetime'"
        ).fetchone()[0]
    assert violations == 0, f"Found {violations} Stage 1 rows using lifetime PD instead of 12m"


def test_ecl_allowance_stage2_uses_lifetime_pd(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_finance.mart_finance_ecl_allowance"
            " WHERE ifrs9_stage = 2"
            "   AND scenario_name != 'probability_weighted'"
            "   AND pd_horizon = '12m'"
        ).fetchone()[0]
    assert violations == 0, f"Found {violations} Stage 2 rows using 12m PD instead of lifetime"


def test_ecl_summary_has_rows(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM mart_finance.mart_finance_ecl_summary"
        ).fetchone()[0]
    assert row_count > 0, "mart_finance_ecl_summary is empty"


def test_ecl_summary_coverage_rate_non_negative(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_finance.mart_finance_ecl_summary"
            " WHERE coverage_rate IS NOT NULL AND coverage_rate < 0"
        ).fetchone()[0]
    assert violations == 0, f"Found {violations} rows with negative coverage_rate"


def test_ecl_allowance_four_rows_per_loan(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    """Each loan should have exactly 4 rows: 3 scenarios + 1 probability_weighted."""
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT loan_id, COUNT(*) AS row_count"
            "  FROM mart_finance.mart_finance_ecl_allowance"
            "  GROUP BY loan_id"
            "  HAVING COUNT(*) != 4"
            ")"
        ).fetchone()[0]
    assert violations == 0, f"Found {violations} loans with row count != 4 in ecl_allowance"


def test_ecl_allowance_discount_factor_is_one_by_default(
    ecl_mart_build: subprocess.CompletedProcess[str],
) -> None:
    """With ecl_include_discount_factor = false (default), all discount_factor = 1.0."""
    assert ecl_mart_build.returncode == 0, ecl_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_finance.mart_finance_ecl_allowance"
            " WHERE scenario_name != 'probability_weighted'"
            "   AND ABS(CAST(discount_factor AS DOUBLE) - 1.0) > 0.000001"
        ).fetchone()[0]
    assert violations == 0, (
        f"Found {violations} rows with discount_factor != 1.0 "
        f"(expected all 1.0 when ecl_include_discount_factor = false)"
    )
