"""Tests for the published-statistics-anchored calibration parameters."""

import math
from itertools import pairwise

import pytest

from loanbook.calibration import (
    SCORE_BANDS,
    AmortizingProductCalibration,
    Calibration,
    RevolvingProductCalibration,
    default_calibration,
    load_calibration_from_loan_performance_data,
)
from loanbook.products import AMORTIZING_PRODUCT_TYPES, ProductType

PROBABILITY_SUM_TOLERANCE = 1e-9
SCORE_BANDS_BEST_TO_WORST = ("super_prime", "prime_plus", "prime", "near_prime", "subprime")


def assert_is_probability_distribution(weights: dict) -> None:
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=PROBABILITY_SUM_TOLERANCE)
    assert all(weight > 0 for weight in weights.values())


def assert_increases_as_band_worsens(values_by_band: dict[str, float]) -> None:
    ordered_best_to_worst = [values_by_band[band] for band in SCORE_BANDS_BEST_TO_WORST]
    assert ordered_best_to_worst[0] > 0
    for better, worse in pairwise(ordered_best_to_worst):
        assert worse > better, values_by_band


def assert_decreases_as_band_worsens(values_by_band: dict[str, float]) -> None:
    ordered_best_to_worst = [values_by_band[band] for band in SCORE_BANDS_BEST_TO_WORST]
    assert ordered_best_to_worst[-1] > 0
    for better, worse in pairwise(ordered_best_to_worst):
        assert worse < better, values_by_band


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


class TestProductMix:
    @pytest.fixture(scope="class")
    def calibration(self) -> Calibration:
        return default_calibration()

    def test_product_mix_covers_exactly_the_four_products(self, calibration: Calibration) -> None:
        assert set(calibration.product_mix) == {product.value for product in ProductType}
        assert_is_probability_distribution(calibration.product_mix)

    def test_mix_is_card_heavy_by_count_and_mortgage_light(self, calibration: Calibration) -> None:
        mix = calibration.product_mix
        assert mix[ProductType.CREDIT_CARD] == max(mix.values())
        assert mix[ProductType.MORTGAGE] == min(mix.values())

    def test_every_amortizing_product_has_a_calibration(self, calibration: Calibration) -> None:
        assert set(calibration.amortizing_products) == {
            product.value for product in AMORTIZING_PRODUCT_TYPES
        }
        for product_calibration in calibration.amortizing_products.values():
            assert isinstance(product_calibration, AmortizingProductCalibration)
        assert isinstance(calibration.credit_card, RevolvingProductCalibration)


class TestAmortizingProductCalibrations:
    @pytest.fixture(scope="class")
    def calibration(self) -> Calibration:
        return default_calibration()

    @pytest.fixture(scope="class", params=sorted(AMORTIZING_PRODUCT_TYPES))
    def product_calibration(
        self, request: pytest.FixtureRequest, calibration: Calibration
    ) -> AmortizingProductCalibration:
        return calibration.amortizing_products[request.param]

    def test_riskier_bands_pay_strictly_higher_rates(
        self, product_calibration: AmortizingProductCalibration
    ) -> None:
        assert_increases_as_band_worsens(product_calibration.annual_interest_rate_by_band)

    def test_riskier_bands_have_strictly_higher_delinquency_entry_hazard(
        self, product_calibration: AmortizingProductCalibration
    ) -> None:
        assert_increases_as_band_worsens(
            product_calibration.monthly_delinquency_entry_hazard_by_band
        )

    def test_safer_bands_prepay_faster(
        self, product_calibration: AmortizingProductCalibration
    ) -> None:
        assert_decreases_as_band_worsens(product_calibration.monthly_prepayment_rate_by_band)

    def test_roll_probabilities_form_distributions_per_delinquent_bucket(
        self, product_calibration: AmortizingProductCalibration
    ) -> None:
        for bucket_name, outcomes in product_calibration.delinquent_roll_probabilities.items():
            assert set(outcomes) == {"cure", "stay", "roll_deeper"}, bucket_name
            assert_is_probability_distribution(outcomes)

    def test_deeper_buckets_are_harder_to_cure_and_roll_forward_more(
        self, product_calibration: AmortizingProductCalibration
    ) -> None:
        rolls = product_calibration.delinquent_roll_probabilities
        assert rolls["dpd_30"]["cure"] > rolls["dpd_60"]["cure"] > rolls["dpd_90_plus"]["cure"]
        assert (
            rolls["dpd_90_plus"]["roll_deeper"]
            > rolls["dpd_60"]["roll_deeper"]
            > rolls["dpd_30"]["roll_deeper"]
        )

    def test_term_mix_is_a_distribution(
        self, product_calibration: AmortizingProductCalibration
    ) -> None:
        assert_is_probability_distribution(product_calibration.term_months_mix)

    def test_amount_bounds_bracket_the_lognormal_median(
        self, product_calibration: AmortizingProductCalibration
    ) -> None:
        assert (
            product_calibration.amount_min_cents
            < product_calibration.amount_log_median_cents
            < product_calibration.amount_max_cents
        )
        assert product_calibration.amount_rounding_cents > 0
        assert product_calibration.amount_log_sigma > 0

    def test_recovery_parameters_are_sane(
        self, product_calibration: AmortizingProductCalibration
    ) -> None:
        assert 0 < product_calibration.recovery_rate_on_defaulted_balance < 1
        assert product_calibration.recovery_lag_months >= 1


class TestProductDifferentiation:
    @pytest.fixture(scope="class")
    def calibration(self) -> Calibration:
        return default_calibration()

    def test_personal_loan_terms_are_lendingclub_style_36_and_60(
        self, calibration: Calibration
    ) -> None:
        personal = calibration.amortizing_products[ProductType.PERSONAL_LOAN]
        assert set(personal.term_months_mix) == {36, 60}

    def test_auto_terms_run_36_to_84_months(self, calibration: Calibration) -> None:
        auto = calibration.amortizing_products[ProductType.AUTO_LOAN]
        assert set(auto.term_months_mix) == {36, 48, 60, 72, 84}

    def test_mortgage_terms_are_30_year_dominated(self, calibration: Calibration) -> None:
        mortgage = calibration.amortizing_products[ProductType.MORTGAGE]
        assert set(mortgage.term_months_mix) == {180, 360}
        assert mortgage.term_months_mix[360] > mortgage.term_months_mix[180]

    def test_collateral_orders_recovery_rates_mortgage_auto_unsecured(
        self, calibration: Calibration
    ) -> None:
        mortgage = calibration.amortizing_products[ProductType.MORTGAGE]
        auto = calibration.amortizing_products[ProductType.AUTO_LOAN]
        personal = calibration.amortizing_products[ProductType.PERSONAL_LOAN]
        assert (
            mortgage.recovery_rate_on_defaulted_balance
            > auto.recovery_rate_on_defaulted_balance
            > personal.recovery_rate_on_defaulted_balance
        )

    def test_secured_products_enter_delinquency_less_often_than_personal_loans(
        self, calibration: Calibration
    ) -> None:
        personal = calibration.amortizing_products[ProductType.PERSONAL_LOAN]
        for product in (ProductType.AUTO_LOAN, ProductType.MORTGAGE):
            secured = calibration.amortizing_products[product]
            for band in SCORE_BANDS_BEST_TO_WORST:
                assert (
                    secured.monthly_delinquency_entry_hazard_by_band[band]
                    < personal.monthly_delinquency_entry_hazard_by_band[band]
                )

    def test_mortgages_price_below_autos_below_personal_loans(
        self, calibration: Calibration
    ) -> None:
        for band in SCORE_BANDS_BEST_TO_WORST:
            mortgage_rate = calibration.amortizing_products[ProductType.MORTGAGE]
            auto_rate = calibration.amortizing_products[ProductType.AUTO_LOAN]
            personal_rate = calibration.amortizing_products[ProductType.PERSONAL_LOAN]
            assert (
                mortgage_rate.annual_interest_rate_by_band[band]
                < auto_rate.annual_interest_rate_by_band[band]
                < personal_rate.annual_interest_rate_by_band[band]
            )


class TestRevolvingCalibration:
    @pytest.fixture(scope="class")
    def card(self) -> RevolvingProductCalibration:
        return default_calibration().credit_card

    def test_riskier_bands_pay_strictly_higher_rates(
        self, card: RevolvingProductCalibration
    ) -> None:
        assert_increases_as_band_worsens(card.annual_interest_rate_by_band)

    def test_better_bands_get_strictly_higher_credit_limits(
        self, card: RevolvingProductCalibration
    ) -> None:
        assert_decreases_as_band_worsens(
            {band: float(limit) for band, limit in card.credit_limit_cents_by_band.items()}
        )

    def test_riskier_bands_run_strictly_higher_target_utilization(
        self, card: RevolvingProductCalibration
    ) -> None:
        assert_increases_as_band_worsens(card.target_utilization_by_band)
        assert all(0 < target < 1 for target in card.target_utilization_by_band.values())

    def test_better_bands_pay_in_full_more_often(self, card: RevolvingProductCalibration) -> None:
        assert_decreases_as_band_worsens(card.pay_in_full_probability_by_band)
        assert all(
            0 < probability < 1 for probability in card.pay_in_full_probability_by_band.values()
        )

    def test_minimum_payment_rule_is_one_percent_plus_interest_with_a_floor(
        self, card: RevolvingProductCalibration
    ) -> None:
        assert card.minimum_payment_principal_rate == 0.01
        assert card.minimum_payment_floor_cents > 0

    def test_spend_replenishment_range_brackets_full_replacement(
        self, card: RevolvingProductCalibration
    ) -> None:
        assert 0 < card.spend_replenishment_min < 1 < card.spend_replenishment_max

    def test_riskier_bands_miss_minimums_more_often(
        self, card: RevolvingProductCalibration
    ) -> None:
        assert_increases_as_band_worsens(card.monthly_delinquency_entry_hazard_by_band)

    def test_roll_probabilities_form_distributions_per_delinquent_bucket(
        self, card: RevolvingProductCalibration
    ) -> None:
        for bucket_name, outcomes in card.delinquent_roll_probabilities.items():
            assert set(outcomes) == {"cure", "stay", "roll_deeper"}, bucket_name
            assert_is_probability_distribution(outcomes)

    def test_unsecured_card_recoveries_are_thin(self, card: RevolvingProductCalibration) -> None:
        assert 0 < card.recovery_rate_on_charged_off_balance < 0.5
        assert card.recovery_lag_months >= 1


class TestBorrowerMixes:
    @pytest.fixture(scope="class")
    def calibration(self) -> Calibration:
        return default_calibration()

    def test_origination_mix_is_a_distribution_over_all_bands(
        self, calibration: Calibration
    ) -> None:
        assert set(calibration.origination_mix_by_band) == {band.name for band in SCORE_BANDS}
        assert_is_probability_distribution(calibration.origination_mix_by_band)

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
