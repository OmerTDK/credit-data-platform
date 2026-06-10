"""Tests for the published-statistics-anchored calibration parameters."""

import math
from itertools import pairwise

import pytest

from loanbook.calibration import (
    SCORE_BANDS,
    Calibration,
    default_calibration,
    load_calibration_from_loan_performance_data,
)

PROBABILITY_SUM_TOLERANCE = 1e-9


def assert_is_probability_distribution(weights: dict) -> None:
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=PROBABILITY_SUM_TOLERANCE)
    assert all(weight > 0 for weight in weights.values())


class TestScoreBands:
    def test_bands_are_the_vantagescore_4_risk_tiers(self) -> None:
        band_ranges = {band.name: (band.score_min, band.score_max) for band in SCORE_BANDS}
        assert band_ranges == {
            "subprime": (300, 600),
            "near_prime": (601, 660),
            "prime": (661, 720),
            "prime_plus": (721, 780),
            "super_prime": (781, 850),
        }

    def test_bands_tile_the_full_score_range_without_gaps(self) -> None:
        ordered = sorted(SCORE_BANDS, key=lambda band: band.score_min)
        assert ordered[0].score_min == 300
        assert ordered[-1].score_max == 850
        for lower, upper in pairwise(ordered):
            assert upper.score_min == lower.score_max + 1


class TestDefaultCalibration:
    @pytest.fixture(scope="class")
    def calibration(self) -> Calibration:
        return default_calibration()

    def test_origination_mix_is_a_distribution_over_all_bands(
        self, calibration: Calibration
    ) -> None:
        assert set(calibration.origination_mix_by_band) == {band.name for band in SCORE_BANDS}
        assert_is_probability_distribution(calibration.origination_mix_by_band)

    def test_riskier_bands_have_strictly_higher_delinquency_entry_hazard(
        self, calibration: Calibration
    ) -> None:
        hazards = calibration.monthly_delinquency_entry_hazard_by_band
        assert (
            hazards["subprime"]
            > hazards["near_prime"]
            > hazards["prime"]
            > hazards["prime_plus"]
            > hazards["super_prime"]
            > 0
        )

    def test_riskier_bands_pay_strictly_higher_rates(self, calibration: Calibration) -> None:
        rates = calibration.annual_interest_rate_by_band
        assert (
            rates["subprime"]
            > rates["near_prime"]
            > rates["prime"]
            > rates["prime_plus"]
            > rates["super_prime"]
            > 0
        )

    def test_safer_bands_prepay_faster(self, calibration: Calibration) -> None:
        smm = calibration.monthly_prepayment_rate_by_band
        assert (
            smm["super_prime"]
            > smm["prime_plus"]
            > smm["prime"]
            > smm["near_prime"]
            > smm["subprime"]
            > 0
        )

    def test_roll_probabilities_form_distributions_per_delinquent_bucket(
        self, calibration: Calibration
    ) -> None:
        for bucket_name, outcomes in calibration.delinquent_roll_probabilities.items():
            assert set(outcomes) == {"cure", "stay", "roll_deeper"}, bucket_name
            assert_is_probability_distribution(outcomes)

    def test_deeper_buckets_are_harder_to_cure_and_roll_forward_more(
        self, calibration: Calibration
    ) -> None:
        rolls = calibration.delinquent_roll_probabilities
        assert rolls["dpd_30"]["cure"] > rolls["dpd_60"]["cure"] > rolls["dpd_90_plus"]["cure"]
        assert (
            rolls["dpd_90_plus"]["roll_deeper"]
            > rolls["dpd_60"]["roll_deeper"]
            > rolls["dpd_30"]["roll_deeper"]
        )

    def test_recovery_parameters_are_sane(self, calibration: Calibration) -> None:
        assert 0 < calibration.recovery_rate_on_defaulted_balance < 0.5
        assert calibration.recovery_lag_months >= 1

    def test_term_mix_is_lendingclub_style_36_and_60(self, calibration: Calibration) -> None:
        assert set(calibration.term_months_mix) == {36, 60}
        assert_is_probability_distribution(calibration.term_months_mix)

    def test_loan_amount_bounds_match_marketplace_lending(self, calibration: Calibration) -> None:
        assert calibration.loan_amount_min_cents == 100_000
        assert calibration.loan_amount_max_cents == 4_000_000

    def test_borrower_attribute_mixes_are_distributions(self, calibration: Calibration) -> None:
        assert_is_probability_distribution(calibration.age_band_mix)
        assert_is_probability_distribution(calibration.income_band_mix)
        assert_is_probability_distribution(calibration.region_mix)

    def test_regions_are_the_four_us_census_regions(self, calibration: Calibration) -> None:
        assert set(calibration.region_mix) == {"northeast", "midwest", "south", "west"}


class TestEmpiricalCalibrationHook:
    def test_loading_from_loan_performance_data_is_a_documented_open_interface(self) -> None:
        with pytest.raises(NotImplementedError, match="calibration"):
            load_calibration_from_loan_performance_data("data/external/loan_performance.csv")
