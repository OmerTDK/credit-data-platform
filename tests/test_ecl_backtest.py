"""Verify ECL parameter validation and backtest logic.

TDD: These tests define the contracts for Phase 4 ECL backtest code.
Run `make ci` after implementing the modules to verify all assertions pass.
"""

from pathlib import Path

import pandas as pd
import pytest

from ecl_backtest.validate_parameters import (
    validate_ccf_rates,
    validate_lgd_rates,
    validate_scenario_weights,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SEEDS_DIR = REPO_ROOT / "seeds"


def load_seed(filename: str) -> pd.DataFrame:
    return pd.read_csv(SEEDS_DIR / filename)


class TestValidateParameters:
    def test_scenario_weights_sum_to_one(self) -> None:
        weights = load_seed("ecl_scenario_weights.csv")
        violations = validate_scenario_weights(weights)
        assert violations == [], f"Scenario weight violations: {violations}"

    def test_lgd_rates_in_unit_interval(self) -> None:
        lgd = load_seed("ecl_lgd_parameters.csv")
        violations = validate_lgd_rates(lgd)
        assert violations == [], f"LGD violations: {violations}"

    def test_ccf_rates_in_unit_interval(self) -> None:
        ead = load_seed("ecl_ead_parameters.csv")
        violations = validate_ccf_rates(ead)
        assert violations == [], f"CCF violations: {violations}"

    def test_invalid_scenario_weights_detected(self) -> None:
        bad_weights = pd.DataFrame(
            {
                "scenario_name": ["baseline", "adverse", "upside"],
                "scenario_weight": [0.5, 0.4, 0.4],
                "pd_scalar": [1.0, 1.4, 0.75],
                "lgd_scalar": [1.0, 1.1, 0.95],
            }
        )
        violations = validate_scenario_weights(bad_weights)
        assert len(violations) == 1
        assert "1.3" in violations[0] or "sum" in violations[0].lower()

    def test_invalid_lgd_rate_detected(self) -> None:
        bad_lgd = pd.DataFrame(
            {
                "product_type": ["personal_loan"],
                "lgd_rate": [1.5],
                "lgd_source_note": ["invalid"],
            }
        )
        violations = validate_lgd_rates(bad_lgd)
        assert len(violations) == 1

    def test_invalid_ccf_rate_detected(self) -> None:
        bad_ead = pd.DataFrame(
            {
                "product_type": ["credit_card"],
                "ccf_rate": [-0.1],
                "ccf_source_note": ["invalid"],
            }
        )
        violations = validate_ccf_rates(bad_ead)
        assert len(violations) == 1

    def test_three_scenarios_loaded(self) -> None:
        weights = load_seed("ecl_scenario_weights.csv")
        assert len(weights) == 3
        assert set(weights["scenario_name"]) == {"baseline", "adverse", "upside"}

    def test_adverse_pd_scalar_exceeds_baseline(self) -> None:
        weights = load_seed("ecl_scenario_weights.csv")
        baseline_pd = weights.loc[weights["scenario_name"] == "baseline", "pd_scalar"].iloc[0]
        adverse_pd = weights.loc[weights["scenario_name"] == "adverse", "pd_scalar"].iloc[0]
        assert adverse_pd > baseline_pd

    def test_upside_pd_scalar_below_baseline(self) -> None:
        weights = load_seed("ecl_scenario_weights.csv")
        baseline_pd = weights.loc[weights["scenario_name"] == "baseline", "pd_scalar"].iloc[0]
        upside_pd = weights.loc[weights["scenario_name"] == "upside", "pd_scalar"].iloc[0]
        assert upside_pd < baseline_pd

    def test_four_product_types_in_lgd(self) -> None:
        lgd = load_seed("ecl_lgd_parameters.csv")
        assert set(lgd["product_type"]) == {"personal_loan", "auto_loan", "mortgage", "credit_card"}

    def test_mortgage_lgd_lower_than_unsecured(self) -> None:
        lgd = load_seed("ecl_lgd_parameters.csv")
        lgd_map = lgd.set_index("product_type")["lgd_rate"].to_dict()
        assert lgd_map["mortgage"] < lgd_map["personal_loan"]
        assert lgd_map["mortgage"] < lgd_map["credit_card"]


class TestBacktestCoverageRatio:
    """Verify that the backtest coverage ratio is within plausible bounds.

    The synthetic book uses stylized parameters, so we expect the coverage
    ratio (realized / modeled) to be within [0.5, 2.0] — broad bounds
    appropriate for a synthetic dataset without fitted PD estimates.
    """

    COVERAGE_MIN = 0.5
    COVERAGE_MAX = 2.0

    @pytest.fixture(scope="class")
    def backtest_results(self) -> pd.DataFrame:
        duckdb_path = REPO_ROOT / "data" / "local" / "credit_platform.duckdb"
        if not duckdb_path.exists():
            pytest.skip("DuckDB not built yet — run make ci first")

        from ecl_backtest.backtest import run_backtest, summarize_backtest

        results = run_backtest()
        return summarize_backtest(results)

    def test_backtest_produces_rows(self, backtest_results: pd.DataFrame) -> None:
        assert len(backtest_results) > 0, "Backtest produced no rows"

    def test_coverage_ratio_within_bounds(self, backtest_results: pd.DataFrame) -> None:
        total_modeled = backtest_results["total_modeled_ecl"].sum()
        total_realized = backtest_results["total_realized_loss"].sum()

        if total_modeled <= 0:
            pytest.skip("No modeled ECL to compute coverage ratio")

        aggregate_coverage = total_realized / total_modeled

        assert self.COVERAGE_MIN <= aggregate_coverage <= self.COVERAGE_MAX, (
            f"Aggregate coverage ratio {aggregate_coverage:.4f} is outside "
            f"[{self.COVERAGE_MIN}, {self.COVERAGE_MAX}]. "
            f"total_modeled={total_modeled:.2f}, total_realized={total_realized:.2f}"
        )
