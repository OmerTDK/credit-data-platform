"""Verify the risk mart layer builds from the DWH into mart_risk tables.

TDD: This test file defines the contracts for Phase 3 risk marts. Run
`make ci` after implementing the mart models to verify all assertions pass.
"""

import os
import subprocess
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DUCKDB_FILE = REPO_ROOT / "data" / "local" / "credit_platform.duckdb"

EXPECTED_MART_RISK_TABLES = {
    ("mart_risk", "mart_risk_roll_rate_matrix"),
    ("mart_risk", "mart_risk_vintage_curve"),
    ("mart_risk", "mart_risk_prepayment_speed"),
}

AMORTIZING_PRODUCT_TYPES = {"personal_loan", "auto_loan", "mortgage"}


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
def risk_mart_build() -> subprocess.CompletedProcess[str]:
    """Build the full pipeline through risk marts."""
    return _run_in_repo(
        [
            "uv",
            "run",
            "dbt",
            "build",
            "--select",
            "int_risk_roll_rate_observations int_risk_vintage_cohort_spine "
            "mart_risk_roll_rate_matrix mart_risk_vintage_curve "
            "mart_risk_prepayment_speed",
        ]
    )


def test_risk_mart_build_succeeds(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, (
        f"dbt build for risk marts failed (exit {risk_mart_build.returncode}):\n"
        f"stdout:\n{risk_mart_build.stdout}\n"
        f"stderr:\n{risk_mart_build.stderr}"
    )


def test_risk_mart_tables_land_in_mart_risk_schema(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        tables = set(
            connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = 'mart_risk' AND table_type = 'BASE TABLE'"
            ).fetchall()
        )
    assert tables >= EXPECTED_MART_RISK_TABLES, (
        f"Missing mart_risk tables: {EXPECTED_MART_RISK_TABLES - tables}; found: {tables}"
    )


def test_roll_rate_matrix_has_rows(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM mart_risk.mart_risk_roll_rate_matrix"
        ).fetchone()[0]
    assert row_count > 0, "mart_risk_roll_rate_matrix is empty"


def test_roll_rate_matrix_all_product_types_present(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        product_types = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT product_type FROM mart_risk.mart_risk_roll_rate_matrix"
            ).fetchall()
        }
    expected = {"personal_loan", "auto_loan", "mortgage", "credit_card"}
    assert product_types == expected, (
        f"Expected all 4 product types in roll rate matrix, got: {product_types}"
    )


def test_roll_rate_matrix_probabilities_sum_to_one(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    """For each (product, score_band, period, from_bucket), SUM(transitions) == at_risk_count."""
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT product_type, score_band, observation_period, from_bucket,"
            "         SUM(transition_loan_count) AS total_transitions,"
            "         MAX(at_risk_loan_count) AS at_risk"
            "  FROM mart_risk.mart_risk_roll_rate_matrix"
            "  GROUP BY product_type, score_band, observation_period, from_bucket"
            "  HAVING ABS(SUM(transition_loan_count) - MAX(at_risk_loan_count)) > 0.001"
            "     AND MAX(at_risk_loan_count) > 0"
            ")"
        ).fetchone()[0]
    assert violations == 0, (
        f"Roll rate probability sums violated in {violations} "
        f"(product, score, period, bucket) groups"
    )


def test_roll_rate_matrix_no_negative_self_transitions(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_risk.mart_risk_roll_rate_matrix"
            " WHERE from_bucket = to_bucket AND transition_loan_count < 0"
        ).fetchone()[0]
    assert violations == 0, f"Found {violations} negative self-transition counts"


def test_roll_rate_matrix_roll_rate_key_unique(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT roll_rate_key)"
            " FROM mart_risk.mart_risk_roll_rate_matrix"
        ).fetchone()
    total, unique_keys = row
    assert total == unique_keys, (
        f"roll_rate_key not unique: {total} rows, {unique_keys} distinct keys"
    )


def test_vintage_curve_has_rows(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM mart_risk.mart_risk_vintage_curve"
        ).fetchone()[0]
    assert row_count > 0, "mart_risk_vintage_curve is empty"


def test_vintage_curve_cumulative_defaults_monotonic(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    """Cumulative default count must be non-decreasing within each cohort/product/score_band."""
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT origination_cohort_quarter, product_type, score_band,"
            "         months_on_book, cumulative_default_count,"
            "         LAG(cumulative_default_count) OVER ("
            "             PARTITION BY origination_cohort_quarter, product_type, score_band"
            "             ORDER BY months_on_book"
            "         ) AS prev_count"
            "  FROM mart_risk.mart_risk_vintage_curve"
            ") sub"
            " WHERE prev_count IS NOT NULL AND cumulative_default_count < prev_count"
        ).fetchone()[0]
    assert violations == 0, f"Cumulative default monotonicity violated in {violations} rows"


def test_vintage_curve_default_rate_in_unit_interval(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_risk.mart_risk_vintage_curve"
            " WHERE cumulative_default_rate < 0 OR cumulative_default_rate > 1"
        ).fetchone()[0]
    assert violations == 0, f"Found {violations} rows with cumulative_default_rate outside [0, 1]"


def test_vintage_curve_prepayment_rate_in_unit_interval(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_risk.mart_risk_vintage_curve"
            " WHERE cumulative_prepayment_rate IS NOT NULL"
            "   AND (cumulative_prepayment_rate < 0 OR cumulative_prepayment_rate > 1)"
        ).fetchone()[0]
    assert violations == 0, (
        f"Found {violations} rows with cumulative_prepayment_rate outside [0, 1]"
    )


def test_vintage_curve_key_unique(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT vintage_curve_key)"
            " FROM mart_risk.mart_risk_vintage_curve"
        ).fetchone()
    total, unique_keys = row
    assert total == unique_keys, (
        f"vintage_curve_key not unique: {total} rows, {unique_keys} distinct keys"
    )


def test_prepayment_speed_amortizing_only(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    """mart_risk_prepayment_speed must contain amortizing products only — no credit_card."""
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        product_types = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT product_type FROM mart_risk.mart_risk_prepayment_speed"
            ).fetchall()
        }
    assert "credit_card" not in product_types, (
        f"credit_card found in mart_risk_prepayment_speed; "
        f"expected amortizing only. Got: {product_types}"
    )
    assert product_types == AMORTIZING_PRODUCT_TYPES, (
        f"Expected {AMORTIZING_PRODUCT_TYPES}, got {product_types}"
    )


def test_prepayment_speed_smm_in_unit_interval(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_risk.mart_risk_prepayment_speed"
            " WHERE smm_rate IS NOT NULL AND (smm_rate < 0 OR smm_rate > 1)"
        ).fetchone()[0]
    assert violations == 0, f"Found {violations} rows with smm_rate outside [0, 1]"


def test_prepayment_speed_cpr_null_iff_smm_null(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    """cpr_rate must be NULL iff smm_rate is NULL."""
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM mart_risk.mart_risk_prepayment_speed"
            " WHERE (smm_rate IS NULL) != (cpr_rate IS NULL)"
        ).fetchone()[0]
    assert violations == 0, (
        f"Found {violations} rows where cpr_rate NULL/non-null doesn't match smm_rate"
    )


def test_prepayment_speed_key_unique(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT prepayment_speed_key)"
            " FROM mart_risk.mart_risk_prepayment_speed"
        ).fetchone()
    total, unique_keys = row
    assert total == unique_keys, (
        f"prepayment_speed_key not unique: {total} rows, {unique_keys} distinct keys"
    )


def test_prepayment_speed_has_rows(
    risk_mart_build: subprocess.CompletedProcess[str],
) -> None:
    assert risk_mart_build.returncode == 0, risk_mart_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM mart_risk.mart_risk_prepayment_speed"
        ).fetchone()[0]
    assert row_count > 0, "mart_risk_prepayment_speed is empty"
