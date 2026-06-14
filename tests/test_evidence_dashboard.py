"""Validate the Evidence dashboard's query layer without Node or a network.

`evidence build` is a Node/npm toolchain step (proven locally, wired as
`make evidence-build`), too heavy and network-dependent for the Python CI. The
CI-safe guarantee instead: every Evidence *source query* under
`bi/sources/credit_platform/` must execute successfully against the same DuckDB
warehouse Evidence reads at build time, and every page must reference a source
query that exists. If a refactor renames a dwh/mart column out from under the
dashboard, this fails in CI — long before anyone runs the Node build.
"""

import os
import re
import subprocess
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DUCKDB_FILE = REPO_ROOT / "data" / "local" / "credit_platform.duckdb"
SOURCE_DIR = REPO_ROOT / "bi" / "sources" / "credit_platform"
PAGES_DIR = REPO_ROOT / "bi" / "pages"

EXPECTED_SOURCE_QUERIES = {
    "portfolio_kpis",
    "origination_by_product",
    "vintage_curve",
    "prepayment_speed",
    "cohort_risk",
    "finops_model_size",
}

EXPECTED_PAGES = {"index.md", "vintage-curves.md", "risk-cohorts.md", "finops.md"}


def _source_sql_files() -> list[Path]:
    return sorted(SOURCE_DIR.glob("*.sql"))


@pytest.fixture(scope="module")
def warehouse_ready() -> None:
    """Build the dwh / mart tables Evidence reads into the DuckDB warehouse.

    The skip guard has been removed: `make generate` (which runs before pytest in
    both CI and `make ci`) ensures the parquet landing files exist. The dbt build
    here is self-sufficient given those parquet files — the same guarantee that
    `semantic_layer_ready` already relies on. A clean CI run (no prior DuckDB)
    must still gate these 6 source-query tests.
    """
    # Include all conformed dims and event-sourced tables so FK relationship
    # tests have their referents present on a clean (no prior DuckDB) build.
    # Without dim_date / dim_product / dim_loan / fct_loan_state_event the
    # relationship tests on the fact tables fail with "Table does not exist".
    build = subprocess.run(
        [
            "uv",
            "run",
            "dbt",
            "build",
            "--exclude",
            "tag:elementary",
            "--select",
            "+dim_date +dim_product +dim_loan +dim_borrower "
            "+dim_loan_current_state +fct_loan_state_event "
            "+fct_loan_origination +fct_loan_lifecycle +fct_payment "
            "+mart_risk_vintage_curve +mart_risk_prepayment_speed",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "DBT_PROFILES_DIR": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, (
        f"dbt build for Evidence-backing tables failed:\n{build.stdout}\n{build.stderr}"
    )


def test_expected_source_queries_present() -> None:
    found = {path.stem for path in _source_sql_files()}
    assert found == EXPECTED_SOURCE_QUERIES, (
        f"source query set drifted: expected {EXPECTED_SOURCE_QUERIES}, found {found}"
    )


def test_expected_pages_present() -> None:
    found = {path.name for path in PAGES_DIR.glob("*.md")}
    assert found == EXPECTED_PAGES, f"page set drifted: expected {EXPECTED_PAGES}, found {found}"


def test_connection_points_at_warehouse() -> None:
    connection = (SOURCE_DIR / "connection.yaml").read_text()
    assert "type: duckdb" in connection, "Evidence source must be a DuckDB connection"
    assert "credit_platform.duckdb" in connection, (
        "Evidence source must point at the dbt-built warehouse file"
    )


@pytest.mark.usefixtures("warehouse_ready")
@pytest.mark.parametrize("sql_file", _source_sql_files(), ids=lambda p: p.stem)
def test_source_query_executes(sql_file: Path) -> None:
    """Each Evidence source query must run against the warehouse and return rows.

    Source queries read dwh/mart tables directly (no Evidence `${...}` template
    parameters at the source layer), so they execute as plain DuckDB SQL.
    """
    sql = sql_file.read_text()
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        rows = connection.execute(sql).fetchall()
    assert len(rows) > 0, f"{sql_file.name} returned no rows"


@pytest.mark.usefixtures("warehouse_ready")
def test_pages_only_reference_existing_source_queries() -> None:
    """Every `credit_platform.<query>` reference in a page must resolve to a file."""
    pattern = re.compile(r"credit_platform\.([a-z_][a-z0-9_]*)")
    for page in PAGES_DIR.glob("*.md"):
        referenced = set(pattern.findall(page.read_text()))
        unknown = referenced - EXPECTED_SOURCE_QUERIES
        assert not unknown, f"{page.name} references unknown source queries: {unknown}"
