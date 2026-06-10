"""Verify the staging layer builds from the parquet landing zone into stg views."""

import os
import subprocess
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LANDING_DIR = REPO_ROOT / "data" / "landing"
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

EXPECTED_STAGING_VIEWS = {
    ("stg", "loanbook__loan"),
    ("stg", "loanbook__borrower"),
    ("stg", "loanbook__monthly_performance"),
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
def staging_build() -> subprocess.CompletedProcess[str]:
    if not LANDING_DIR.exists():
        generated = _run_in_repo(GENERATE_COMMAND)
        assert generated.returncode == 0, (
            f"loanbook generate failed (exit {generated.returncode}):\n{generated.stderr}"
        )
    DUCKDB_FILE.parent.mkdir(parents=True, exist_ok=True)
    return _run_in_repo(["uv", "run", "dbt", "build", "--select", "staging"])


def test_staging_build_succeeds(staging_build: subprocess.CompletedProcess[str]) -> None:
    assert staging_build.returncode == 0, (
        f"dbt build --select staging failed (exit {staging_build.returncode}):\n"
        f"stdout:\n{staging_build.stdout}\n"
        f"stderr:\n{staging_build.stderr}"
    )


def test_staging_views_land_in_stg_schema(
    staging_build: subprocess.CompletedProcess[str],
) -> None:
    assert staging_build.returncode == 0, staging_build.stdout
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        views = set(
            connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = 'stg' AND table_type = 'VIEW'"
            ).fetchall()
        )
    assert EXPECTED_STAGING_VIEWS <= views, (
        f"Missing staging views: {EXPECTED_STAGING_VIEWS - views}; found: {views}"
    )


def test_staging_row_counts_match_landing_parquet(
    staging_build: subprocess.CompletedProcess[str],
) -> None:
    assert staging_build.returncode == 0, staging_build.stdout
    landing_globs = {
        "loanbook__loan": "data/landing/loans/*.parquet",
        "loanbook__borrower": "data/landing/borrowers/*.parquet",
        "loanbook__monthly_performance": "data/landing/monthly_performance/*/*.parquet",
    }
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        for view_name, landing_glob in landing_globs.items():
            view_count = connection.execute(
                f"SELECT COUNT(*) FROM stg.{view_name}"
            ).fetchone()[0]
            landing_count = connection.execute(
                f"SELECT COUNT(*) FROM read_parquet('{REPO_ROOT / landing_glob}')"
            ).fetchone()[0]
            assert view_count == landing_count, (
                f"stg.{view_name} has {view_count} rows, landing has {landing_count}"
            )
