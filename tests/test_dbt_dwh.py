"""Verify the DWH dimensional layer builds from staging into dwh tables."""

import os
import subprocess
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DUCKDB_FILE = REPO_ROOT / "data" / "local" / "credit_platform.duckdb"

GENERATE_COMMAND = [
    "uv",
    "run",
    "python",
    "-m",
    "loanbook",
    "generate",
    "--seed",
    "42",
    "--cohorts",
    "24",
    "--loans-per-cohort",
    "500",
]

EXPECTED_DWH_TABLES = {
    ("dwh", "dim_date"),
    ("dwh", "dim_product"),
    ("dwh", "dim_loan"),
    ("dwh", "dim_borrower"),
    ("dwh", "dim_loan_current_state"),
    ("dwh", "fct_loan_origination"),
    ("dwh", "fct_payment"),
    ("dwh", "fct_loan_state_event"),
    ("dwh", "fct_loan_lifecycle"),
}


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
def dwh_build() -> subprocess.CompletedProcess[str]:
    generated = _run_in_repo(GENERATE_COMMAND)
    assert generated.returncode == 0, (
        f"loanbook generate failed (exit {generated.returncode}):\n{generated.stderr}"
    )
    DUCKDB_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Build the DWH plus its ancestors. The bare `intermediate` selector also
    # pulls in the ECL and risk intermediates, which depend on the ECL seeds and
    # the mart_risk tables. Select the DWH facts/dims with `+...` so every
    # ancestor (staging, intermediate, seeds) is built, but stop short of the
    # downstream risk and ECL marts (those have their own build fixtures).
    # Exclude tag:elementary — the Elementary anomaly/schema tests on fct_payment
    # need the full Elementary model layer (built only in the complete dbt build
    # the Dagster materialization runs), not this scoped DWH build.
    return _run_in_repo(
        [
            "uv",
            "run",
            "dbt",
            "build",
            "--exclude",
            "tag:elementary",
            "--select",
            "+dim_date +dim_product +dim_loan +dim_borrower +dim_loan_current_state "
            "+fct_loan_origination +fct_payment +fct_loan_state_event +fct_loan_lifecycle",
        ]
    )


def test_dwh_build_succeeds(dwh_build: subprocess.CompletedProcess[str]) -> None:
    assert dwh_build.returncode == 0, (
        f"dbt build --select staging intermediate dwh failed "
        f"(exit {dwh_build.returncode}):\n"
        f"stdout:\n{dwh_build.stdout}\n"
        f"stderr:\n{dwh_build.stderr}"
    )


def test_dwh_tables_land_in_dwh_schema(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        tables = set(
            connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = 'dwh' AND table_type = 'BASE TABLE'"
            ).fetchall()
        )
    assert tables >= EXPECTED_DWH_TABLES, (
        f"Missing DWH tables: {EXPECTED_DWH_TABLES - tables}; found: {tables}"
    )


def test_dim_date_covers_full_range(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row = connection.execute(
            "SELECT MIN(full_date), MAX(full_date), COUNT(*) FROM dwh.dim_date"
        ).fetchone()
    min_date, max_date, row_count = row
    assert str(min_date) == "2020-01-01", f"dim_date min date wrong: {min_date}"
    assert str(max_date) == "2029-12-31", f"dim_date max date wrong: {max_date}"
    assert row_count == 3653, f"dim_date row count wrong: {row_count}"


def test_dim_product_has_all_four_products(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        products = {
            row[0]
            for row in connection.execute("SELECT product_type FROM dwh.dim_product").fetchall()
        }
    expected = {"personal_loan", "auto_loan", "mortgage", "credit_card"}
    assert products == expected, f"dim_product products wrong: {products}"


def test_dim_loan_grain_is_one_row_per_loan(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        loan_count = connection.execute("SELECT COUNT(*) FROM dwh.dim_loan").fetchone()[0]
        unique_loans = connection.execute(
            "SELECT COUNT(DISTINCT loan_id) FROM dwh.dim_loan"
        ).fetchone()[0]
    assert loan_count == unique_loans, (
        f"dim_loan has duplicate loan_ids: {loan_count} rows, {unique_loans} unique"
    )
    assert loan_count == 12000, f"Expected 12000 loans, got {loan_count}"


def test_dim_borrower_scd2_one_current_row_per_borrower(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT borrower_id, COUNT(*) AS cnt"
            "  FROM dwh.dim_borrower"
            "  WHERE _is_current"
            "  GROUP BY borrower_id"
            "  HAVING cnt != 1"
            ")"
        ).fetchone()[0]
    assert violations == 0, f"SCD2 invariant violated: {violations} borrowers have != 1 current row"


def test_dim_borrower_scd2_valid_from_monotonic(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT borrower_id, version_number, _valid_from,"
            "         LAG(_valid_from) OVER ("
            "             PARTITION BY borrower_id ORDER BY version_number"
            "         ) AS prev_valid_from"
            "  FROM dwh.dim_borrower"
            ") sub"
            " WHERE prev_valid_from IS NOT NULL AND prev_valid_from >= _valid_from"
        ).fetchone()[0]
    assert violations == 0, f"SCD2 valid_from ordering violated: {violations} rows"


def test_dim_borrower_scd2_valid_to_equals_next_valid_from(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    """For non-current SCD2 rows, _valid_to must equal the immediately next _valid_from.

    This verifies the LEAD(_valid_from, 1) offset is correct: a wrong offset (e.g.
    LEAD(_valid_from, 2)) creates a 1-month gap in the timeline for borrowers with
    multiple versions, but all other SCD2 tests (monotonic, one-current) stay green.
    """
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT borrower_id, version_number, _valid_to,"
            "         LEAD(_valid_from) OVER ("
            "             PARTITION BY borrower_id ORDER BY version_number"
            "         ) AS next_valid_from"
            "  FROM dwh.dim_borrower"
            ") sub"
            " WHERE next_valid_from IS NOT NULL AND _valid_to != next_valid_from"
        ).fetchone()[0]
    assert violations == 0, (
        f"SCD2 _valid_to chain broken: {violations} rows where _valid_to != next _valid_from. "
        "This indicates a wrong LEAD offset in dim_borrower.sql."
    )


def test_fct_payment_grain_is_loan_month(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT loan_id || '|' || months_on_book::varchar)"
            " FROM dwh.fct_payment"
        ).fetchone()
    total, unique_grain = row
    assert total == unique_grain, (
        f"fct_payment grain violated: {total} rows, {unique_grain} unique (loan_id, months_on_book)"
    )
    assert total == 255131, f"Expected 255131 payment rows, got {total}"


def test_no_negative_ending_balances(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        neg_count = connection.execute(
            "SELECT COUNT(*) FROM dwh.fct_payment WHERE ending_balance_amount < 0"
        ).fetchone()[0]
    assert neg_count == 0, f"Found {neg_count} rows with negative ending_balance_amount"


def test_fct_loan_lifecycle_grain_is_one_row_per_loan(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        row = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT loan_id) FROM dwh.fct_loan_lifecycle"
        ).fetchone()
    total, unique_loans = row
    assert total == unique_loans, (
        f"fct_loan_lifecycle grain violated: {total} rows, {unique_loans} unique loans"
    )
    assert total == 12000, f"Expected 12000 lifecycle rows, got {total}"


def test_lifecycle_milestone_ordering(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    """Lifecycle milestone invariants: set-membership and ordering.

    Invariant 1 (set-membership): a later delinquency stage cannot appear without
    all earlier stages. dpd_60 requires prior dpd_30; dpd_90_plus requires prior
    dpd_60; default requires prior dpd_90_plus. This is enforced by the state
    machine and must propagate into the lifecycle fact.

    Invariant 2 (ordering): when both milestones are present, the earlier stage
    must have a lower report_month than the later one.
    """
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        violations = connection.execute(
            "SELECT COUNT(*) FROM dwh.fct_loan_lifecycle"
            " WHERE"
            # Invariant 1: set-membership gaps are impossible per the state machine.
            "   (first_dpd60_month IS NOT NULL AND first_dpd30_month IS NULL)"
            "   OR (first_dpd90_month IS NOT NULL AND first_dpd60_month IS NULL)"
            "   OR (default_month IS NOT NULL AND first_dpd90_month IS NULL)"
            # Invariant 2: when both milestones are present the earlier one must precede.
            "   OR (first_dpd60_month IS NOT NULL AND first_dpd30_month IS NOT NULL"
            "       AND first_dpd60_month < first_dpd30_month)"
            "   OR (first_dpd90_month IS NOT NULL AND first_dpd60_month IS NOT NULL"
            "       AND first_dpd90_month < first_dpd60_month)"
            "   OR (default_month IS NOT NULL AND first_dpd90_month IS NOT NULL"
            "       AND default_month < first_dpd90_month)"
        ).fetchone()[0]
    assert violations == 0, f"Lifecycle milestone invariants violated: {violations} loans"


def test_current_state_matches_direct_computation(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        mismatches = connection.execute(
            "WITH direct AS ("
            "  SELECT loan_id, loan_status AS direct_status, delinquency_bucket AS direct_bucket"
            "  FROM ("
            "    SELECT loan_id, loan_status, delinquency_bucket,"
            "           ROW_NUMBER() OVER (PARTITION BY loan_id ORDER BY months_on_book DESC) AS rn"
            "    FROM int.int_monthly_performance"
            "  ) WHERE rn = 1"
            ")"
            " SELECT COUNT(*) FROM dwh.dim_loan_current_state cs"
            " JOIN direct ON cs.loan_id = direct.loan_id"
            " WHERE cs.current_loan_status != direct.direct_status"
            "    OR cs.current_delinquency_bucket != direct.direct_bucket"
        ).fetchone()[0]
    assert mismatches == 0, (
        f"Event-stream current state diverges from direct computation: {mismatches} mismatches"
    )


def test_event_stream_valid_delinquency_transitions(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    """Delinquency transitions must match LEGAL_BUCKET_TRANSITIONS in state_machine.py.

    Only dpd_90_plus -> default is a legal skip-to-default; current/dpd_30/dpd_60
    must progress one bucket at a time. Allowing current/dpd_30/dpd_60 -> default
    would mask generator bugs that produce illegal transitions.
    """
    assert dwh_build.returncode == 0, dwh_build.stdout
    # Must mirror LEGAL_BUCKET_TRANSITIONS in src/loanbook/state_machine.py exactly.
    # Self-transitions are excluded: only transitions that produce a *changed* bucket appear.
    valid_transitions = {
        "current": {"dpd_30"},
        "dpd_30": {"current", "dpd_60"},
        "dpd_60": {"current", "dpd_90_plus"},
        "dpd_90_plus": {"current", "default"},
        "default": set(),
    }
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        events = connection.execute(
            "SELECT from_delinquency_bucket, to_delinquency_bucket, COUNT(*)"
            " FROM dwh.fct_loan_state_event"
            " WHERE event_type = 'delinquency_transition'"
            " GROUP BY 1, 2"
        ).fetchall()
    for from_bucket, to_bucket, count in events:
        allowed = valid_transitions.get(from_bucket, set())
        assert to_bucket in allowed, (
            f"Invalid delinquency transition {from_bucket} -> {to_bucket} ({count} occurrences)"
        )


def test_dpd90_to_default_is_delinquency_transition(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    """dpd_90_plus -> default must be delinquency_transition, not lifecycle_transition.

    When a loan defaults it simultaneously changes delinquency_bucket (dpd_90_plus -> default)
    and loan_status (active -> defaulted). The delinquency change is the analytically meaningful
    event for roll-rate queries; classifying it as lifecycle_transition silently drops it from
    delinquency roll-rate analyses.
    """
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        rows = connection.execute(
            "SELECT event_type, COUNT(*) AS cnt"
            " FROM dwh.fct_loan_state_event"
            " WHERE from_delinquency_bucket = 'dpd_90_plus'"
            "   AND to_delinquency_bucket = 'default'"
            " GROUP BY event_type"
        ).fetchall()
    result = {row[0]: row[1] for row in rows}
    lifecycle_count = result.get("lifecycle_transition", 0)
    delinquency_count = result.get("delinquency_transition", 0)
    assert lifecycle_count == 0, (
        f"dpd_90_plus -> default transitions misclassified as lifecycle_transition: "
        f"{lifecycle_count} rows (should be 0); delinquency_transition count: {delinquency_count}"
    )
    assert delinquency_count > 0, (
        "Expected at least one dpd_90_plus -> default delinquency_transition event"
    )


def test_no_lifecycle_transition_changes_delinquency_bucket(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    """No lifecycle_transition row may simultaneously be a delinquency bucket change.

    A lifecycle_transition (paid_off, defaulted, recovery_complete) that also changes
    the delinquency bucket means the CASE order in fct_loan_state_event is wrong:
    the delinquency change takes analytical priority and must be classified as
    delinquency_transition.
    """
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM dwh.fct_loan_state_event"
            " WHERE event_type = 'lifecycle_transition'"
            "   AND from_delinquency_bucket IS NOT NULL"
            "   AND from_delinquency_bucket != to_delinquency_bucket"
        ).fetchone()[0]
    assert count == 0, (
        f"Found {count} lifecycle_transition rows that also change delinquency_bucket; "
        "these should be classified as delinquency_transition"
    )


def test_fct_loan_state_event_all_loans_have_origination(
    dwh_build: subprocess.CompletedProcess[str],
) -> None:
    assert dwh_build.returncode == 0, dwh_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        origination_count = connection.execute(
            "SELECT COUNT(DISTINCT loan_id) FROM dwh.fct_loan_state_event"
            " WHERE event_type = 'origination'"
        ).fetchone()[0]
    assert origination_count == 12000, (
        f"Expected 12000 loans with origination events, got {origination_count}"
    )
