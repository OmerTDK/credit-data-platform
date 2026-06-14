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

# Pinned values, derived independently from the warehouse (fixed seed -> stable).
#
# origination_volume = SUM(principal_amount) over 5,397 amortizing loans
#   (credit cards carry NULL principal_amount and are excluded by SUM; see
#   _sem_originations.yml: measure description says "amortizing products").
# default_rate       = 660 defaulted loans / 12,000 lifecycle loans = 0.055
# cpr                = 1 - (1 - SMM)^12, book-level aggregated SMM
#                      SMM = SUM(prepaid_balance) / SUM(performing_pool_balance)
#                      across all rows in mart_risk_prepayment_speed.
# portfolio_yield    = SUM(interest_charged_amount) / SUM(beginning_balance_amount)
#                      from dwh.fct_payment.
# delinquency_rate   = delinquent loan-months / total loan-months from fct_payment.
# avg_balance        = AVG(ending_balance_amount) from dwh.fct_payment.
# vintage_loss_curve = SUM(cumulative_default_count) / SUM(cohort_loan_count)
#                      across all rows in mart_risk_vintage_curve (global grain).
PINNED_ORIGINATION_VOLUME = 430_503_900.00
PINNED_DEFAULT_RATE = 0.055
PINNED_DEFAULTED_LOANS = 660
PINNED_LIFECYCLE_LOANS = 12_000
PINNED_CPR = 0.07854232402481887
PINNED_PORTFOLIO_YIELD = 0.006734355914638508
PINNED_DELINQUENCY_RATE = 0.04524342396651132
PINNED_AVG_BALANCE = 35301.127473964356
PINNED_VINTAGE_LOSS_CURVE = 0.028772108843537415


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
            # Include all conformed dims so FK relationship tests on the facts
            # have their referents present on a clean (no prior DuckDB) build.
            # Without dim_date, dim_product, dim_loan, dim_borrower, and the
            # event-sourced dims, dbt relationship tests fail with "Table does
            # not exist" even though the metric queries themselves don't need them.
            "+dim_date +dim_product +dim_loan +dim_borrower "
            "+dim_loan_current_state +fct_loan_state_event "
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
    # Parse only lines that contain the bullet marker "•" — the stable MetricFlow
    # output format is "• metric_name: description". Filtering on "•" avoids
    # treating header or warning lines (which may contain ":") as metric entries.
    listed = {
        line.split("•", 1)[-1].split(":")[0].strip()
        for line in result.stdout.replace("\r", "\n").splitlines()
        if "•" in line
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
    """default_rate must equal defaulted_loans / lifecycle_loans = 0.055 exactly.

    Also pins the component building-block metrics so a denominator-model swap
    (e.g. routing the lifecycle count through fct_loan_origination instead of
    fct_loan_lifecycle) is caught even when both tables have the same row count.
    The two source models are currently both 12,000 rows; the component pins bind
    the ratio to the correct source model independently of the coincidental count.
    """
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
    # Component pins: independently verify the numerator and denominator metrics
    # so a denominator-source swap (lifecycle → originations, same count) fails.
    defaulted_loans_val = _mf_scalar("defaulted_loans")
    assert defaulted_loans_val == pytest.approx(PINNED_DEFAULTED_LOANS, abs=0.5), (
        f"defaulted_loans component drifted: {defaulted_loans_val} vs {PINNED_DEFAULTED_LOANS}"
    )
    lifecycle_loans_val = _mf_scalar("lifecycle_loans")
    assert lifecycle_loans_val == pytest.approx(PINNED_LIFECYCLE_LOANS, abs=0.5), (
        f"lifecycle_loans component drifted: {lifecycle_loans_val} vs {PINNED_LIFECYCLE_LOANS}"
    )
    # Verify lifecycle_loans is sourced from fct_loan_lifecycle (not fct_loan_origination)
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        lifecycle_direct = connection.execute(
            "SELECT COUNT(*) FROM dwh.fct_loan_lifecycle"
        ).fetchone()[0]
    assert lifecycle_loans_val == pytest.approx(lifecycle_direct, abs=0.5), (
        "lifecycle_loans metric does not match fct_loan_lifecycle row count"
    )


@pytest.mark.usefixtures("semantic_layer_ready")
def test_cpr_matches_pinned_value() -> None:
    """cpr must equal 1 - (1 - book_level_SMM)^12 from an independent derivation.

    The CPR formula has a non-trivial annualization exponent (12). Changing it to
    1 makes CPR = SMM (~10-20x smaller) — a surviving mutant if only returncode==0
    is checked. This pin catches that mutation: the annualized value differs from
    SMM by ~10x. The pin is derived independently as:
        SMM = SUM(prepaid_balance) / SUM(performing_pool_balance)
        CPR = 1 - (1 - SMM)^12
    both computed directly from mart_risk.mart_risk_prepayment_speed.
    """
    value = _mf_scalar("cpr")
    assert value == pytest.approx(PINNED_CPR, rel=1e-4), (
        f"cpr drifted: MetricFlow {value} vs pinned {PINNED_CPR}"
    )
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        smm = connection.execute(
            "SELECT SUM(prepaid_balance) / NULLIF(SUM(performing_pool_balance), 0) "
            "FROM mart_risk.mart_risk_prepayment_speed"
        ).fetchone()[0]
    warehouse_cpr = 1 - (1 - smm) ** 12
    assert warehouse_cpr == pytest.approx(PINNED_CPR, rel=1e-6)
    assert value == pytest.approx(warehouse_cpr, rel=1e-4), (
        f"cpr MetricFlow {value} diverges from warehouse derivation {warehouse_cpr}"
    )


@pytest.mark.usefixtures("semantic_layer_ready")
def test_portfolio_yield_matches_pinned_value() -> None:
    """portfolio_yield must equal interest_charged / beginning_balance.

    Swapping numerator and denominator would produce ~148x the correct value.
    This pin catches such a mutation.
    """
    value = _mf_scalar("portfolio_yield")
    assert value == pytest.approx(PINNED_PORTFOLIO_YIELD, rel=1e-4), (
        f"portfolio_yield drifted: MetricFlow {value} vs pinned {PINNED_PORTFOLIO_YIELD}"
    )
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        interest, beg_bal = connection.execute(
            "SELECT SUM(interest_charged_amount), SUM(beginning_balance_amount) "
            "FROM dwh.fct_payment"
        ).fetchone()
    warehouse_yield = float(interest) / float(beg_bal)
    assert warehouse_yield == pytest.approx(PINNED_PORTFOLIO_YIELD, rel=1e-6)
    assert value == pytest.approx(warehouse_yield, rel=1e-4)


@pytest.mark.usefixtures("semantic_layer_ready")
def test_delinquency_rate_matches_pinned_value() -> None:
    """delinquency_rate must equal delinquent_loan_months / total_loan_months.

    The delinquency buckets are 'dpd_30', 'dpd_60', 'dpd_90_plus', 'default'.
    Changing the bucket list or swapping numerator and denominator is caught here.
    """
    value = _mf_scalar("delinquency_rate")
    assert value == pytest.approx(PINNED_DELINQUENCY_RATE, rel=1e-4), (
        f"delinquency_rate drifted: MetricFlow {value} vs pinned {PINNED_DELINQUENCY_RATE}"
    )
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        delinquent, total = connection.execute(
            "SELECT "
            "  SUM(CASE WHEN delinquency_bucket IN "
            "    ('dpd_30', 'dpd_60', 'dpd_90_plus', 'default') THEN 1 ELSE 0 END), "
            "  COUNT(*) "
            "FROM dwh.fct_payment"
        ).fetchone()
    warehouse_rate = delinquent / total
    assert warehouse_rate == pytest.approx(PINNED_DELINQUENCY_RATE, rel=1e-6)
    assert value == pytest.approx(warehouse_rate, rel=1e-4)


@pytest.mark.usefixtures("semantic_layer_ready")
def test_avg_balance_matches_pinned_value() -> None:
    """avg_balance must equal AVG(ending_balance_amount) from fct_payment."""
    value = _mf_scalar("avg_balance")
    assert value == pytest.approx(PINNED_AVG_BALANCE, rel=1e-4), (
        f"avg_balance drifted: MetricFlow {value} vs pinned {PINNED_AVG_BALANCE}"
    )
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        warehouse_avg = connection.execute(
            "SELECT AVG(ending_balance_amount) FROM dwh.fct_payment"
        ).fetchone()[0]
    assert warehouse_avg == pytest.approx(PINNED_AVG_BALANCE, rel=1e-6)
    assert value == pytest.approx(warehouse_avg, rel=1e-4)


@pytest.mark.usefixtures("semantic_layer_ready")
def test_vintage_loss_curve_matches_pinned_value() -> None:
    """vintage_loss_curve must equal cumulative_defaults / cohort_exposure at global grain.

    The ungrouped scalar is the ratio of sums across all rows in
    mart_risk_vintage_curve (all cohorts, all products, all MOBs).
    """
    value = _mf_scalar("vintage_loss_curve")
    assert value == pytest.approx(PINNED_VINTAGE_LOSS_CURVE, rel=1e-4), (
        f"vintage_loss_curve drifted: MetricFlow {value} vs pinned {PINNED_VINTAGE_LOSS_CURVE}"
    )
    with duckdb.connect(str(DUCKDB_FILE), read_only=True) as connection:
        cum_defaults, cohort_exposure = connection.execute(
            "SELECT SUM(cumulative_default_count), SUM(cohort_loan_count) "
            "FROM mart_risk.mart_risk_vintage_curve"
        ).fetchone()
    warehouse_vlc = cum_defaults / cohort_exposure
    assert warehouse_vlc == pytest.approx(PINNED_VINTAGE_LOSS_CURVE, rel=1e-6)
    assert value == pytest.approx(warehouse_vlc, rel=1e-4)


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
