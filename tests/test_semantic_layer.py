"""Verify the MetricFlow semantic layer resolves and returns governed values.

The semantic layer defines every metric once over the dwh/marts so BI tools and
the downstream llm-analyst share one definition. These tests are the guardrail
against silent metric drift: two values are pinned from an independent direct
DuckDB derivation, so any change to a metric definition that moves the number
fails CI.

Why `mf query` and not a direct SQL check: the point is to exercise the *real*
MetricFlow query path (semantic manifest -> SQL render -> DuckDB), which is what
proves DuckDB is a supported MetricFlow engine and that the YAML compiles to the
arithmetic we expect.
"""

import csv
import os
import subprocess
import tempfile
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DUCKDB_FILE = REPO_ROOT / "data" / "local" / "credit_platform.duckdb"

# The seven governed metrics this phase delivers (building-block simple metrics
# that exist only to feed ratios are intentionally not in this list).
GOVERNED_METRICS = {
    "default_rate",
    "cpr",
    "portfolio_yield",
    "vintage_loss_curve",
    "origination_volume",
    "avg_balance",
    "delinquency_rate",
}

# Pinned values, derived independently from the warehouse (fixed seed -> stable):
#   origination_volume = SUM(principal_amount) over 12,000 originated loans
#   default_rate       = 660 defaulted loans / 12,000 loans = 0.055 exactly
PINNED_ORIGINATION_VOLUME = 430_503_900.00
PINNED_DEFAULT_RATE = 0.055


def _run_in_repo(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env={**os.environ, "DBT_PROFILES_DIR": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )


def _mf_scalar(metric: str) -> float:
    """Run `mf query --metrics <metric>` and return the single scalar result.

    Uses `--csv` for full-precision output: the default pretty-printed table
    renders large numbers in 6-significant-figure scientific notation, which
    would let a several-thousand-unit drift hide inside the rounding. The CSV
    carries the exact value, so the pinned assertions can be tight.
    """
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as handle:
        out_path = Path(handle.name)
    try:
        result = _run_in_repo(
            ["uv", "run", "mf", "query", "--metrics", metric, "--csv", str(out_path)]
        )
        assert result.returncode == 0, (
            f"mf query for {metric} failed (exit {result.returncode}):\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        with out_path.open(newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        assert len(rows) == 1, f"expected one scalar row for {metric}, got {rows}"
        return float(rows[0][metric])
    finally:
        out_path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def semantic_layer_ready() -> None:
    """Build the warehouse, marts, and the MetricFlow time spine, then parse.

    Ancestor selection (`+model`) makes the fixture independent of test ordering.
    The time spine is required for MetricFlow metric_time aggregation; the marts
    back the prepayment / vintage metrics.
    """
    build = _run_in_repo(
        [
            "uv",
            "run",
            "dbt",
            "build",
            "--exclude",
            "tag:elementary",
            "--select",
            "+metricflow_time_spine +fct_loan_lifecycle +fct_loan_origination "
            "+fct_payment +mart_risk_prepayment_speed +mart_risk_vintage_curve",
        ]
    )
    assert build.returncode == 0, (
        f"dbt build for semantic-layer ancestors failed (exit {build.returncode}):\n"
        f"stdout:\n{build.stdout}\nstderr:\n{build.stderr}"
    )
    parse = _run_in_repo(["uv", "run", "dbt", "parse"])
    assert parse.returncode == 0, (
        f"dbt parse of the semantic manifest failed (exit {parse.returncode}):\n"
        f"stdout:\n{parse.stdout}\nstderr:\n{parse.stderr}"
    )


@pytest.mark.usefixtures("semantic_layer_ready")
def test_semantic_manifest_validates() -> None:
    """mf validate-configs must pass against the built DuckDB warehouse."""
    result = _run_in_repo(["uv", "run", "mf", "validate-configs"])
    assert result.returncode == 0, (
        f"mf validate-configs failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@pytest.mark.usefixtures("semantic_layer_ready")
def test_all_governed_metrics_listed() -> None:
    """Every governed metric must appear in `mf list metrics`."""
    result = _run_in_repo(["uv", "run", "mf", "list", "metrics"])
    assert result.returncode == 0, result.stderr
    listed = {
        line.split(":")[0].lstrip("•").strip()
        for line in result.stdout.replace("\r", "\n").splitlines()
        if "•" in line or ":" in line
    }
    missing = GOVERNED_METRICS - listed
    assert not missing, f"Metrics not exposed by MetricFlow: {missing}; listed: {listed}"


@pytest.mark.usefixtures("semantic_layer_ready")
@pytest.mark.parametrize("metric", sorted(GOVERNED_METRICS))
def test_governed_metric_resolves(metric: str) -> None:
    """Each governed metric must compile to SQL and execute on DuckDB."""
    result = _run_in_repo(["uv", "run", "mf", "query", "--metrics", metric])
    assert result.returncode == 0, (
        f"mf query for {metric} did not resolve (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@pytest.mark.usefixtures("semantic_layer_ready")
def test_origination_volume_matches_pinned_value() -> None:
    """origination_volume must equal the independently-derived warehouse total.

    A change to the origination_volume measure (e.g. summing the wrong column or
    adding credit_limit) moves this number and fails the test.
    """
    value = _mf_scalar("origination_volume")
    # Full-precision CSV output -> assert to the cent. A drift of even one loan's
    # principal moves this well outside 0.01.
    assert value == pytest.approx(PINNED_ORIGINATION_VOLUME, abs=0.01), (
        f"origination_volume drifted: MetricFlow {value} vs pinned {PINNED_ORIGINATION_VOLUME}"
    )
    # Cross-check the pin against the warehouse so the pin itself can't go stale.
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        warehouse_total = float(
            connection.execute(
                "SELECT SUM(principal_amount) FROM dwh.fct_loan_origination"
            ).fetchone()[0]
        )
    assert warehouse_total == pytest.approx(PINNED_ORIGINATION_VOLUME, rel=1e-6)


@pytest.mark.usefixtures("semantic_layer_ready")
def test_default_rate_matches_pinned_value() -> None:
    """default_rate must equal defaulted_loans / lifecycle_loans = 0.055 exactly."""
    value = _mf_scalar("default_rate")
    assert value == pytest.approx(PINNED_DEFAULT_RATE, abs=1e-6), (
        f"default_rate drifted: MetricFlow {value} vs pinned {PINNED_DEFAULT_RATE}"
    )
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        defaulted, total = connection.execute(
            "SELECT SUM(CASE WHEN has_defaulted THEN 1 ELSE 0 END), COUNT(*) "
            "FROM dwh.fct_loan_lifecycle"
        ).fetchone()
    assert defaulted / total == pytest.approx(PINNED_DEFAULT_RATE, abs=1e-6)


@pytest.mark.usefixtures("semantic_layer_ready")
def test_default_rate_resolves_by_credit_tier() -> None:
    """default_rate (lifecycle model) must be groupable by credit_tier.

    credit_tier lives on the originations semantic model; reaching it from
    default_rate proves the cross-model join over the shared `loan` entity, the
    core governed-semantic-layer behaviour.
    """
    result = _run_in_repo(
        [
            "uv",
            "run",
            "mf",
            "query",
            "--metrics",
            "default_rate",
            "--group-by",
            "loan__credit_tier",
        ]
    )
    assert result.returncode == 0, (
        f"default_rate by credit_tier failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "subprime" in result.stdout, (
        f"expected credit_tier values in output; got:\n{result.stdout}"
    )
