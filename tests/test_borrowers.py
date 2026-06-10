"""Tests for borrower attribute generation."""

import numpy as np

from loanbook.borrowers import Borrower, generate_borrower
from loanbook.calibration import SCORE_BAND_BY_NAME, default_calibration

SAMPLE_SIZE = 500


def generate_sample(seed: int) -> list[Borrower]:
    calibration = default_calibration()
    rng = np.random.default_rng(seed)
    return [generate_borrower(f"B-{index:06d}", calibration, rng) for index in range(SAMPLE_SIZE)]


class TestGenerateBorrower:
    def test_borrower_carries_the_requested_id(self) -> None:
        sample = generate_sample(seed=1)
        assert sample[0].borrower_id == "B-000000"

    def test_attributes_come_from_the_calibrated_categories(self) -> None:
        calibration = default_calibration()
        for borrower in generate_sample(seed=1):
            assert borrower.age_band in calibration.age_band_mix
            assert borrower.income_band in calibration.income_band_mix
            assert borrower.region in calibration.region_mix
            assert borrower.score_band in SCORE_BAND_BY_NAME

    def test_credit_score_lies_inside_its_band(self) -> None:
        for borrower in generate_sample(seed=2):
            band = SCORE_BAND_BY_NAME[borrower.score_band]
            assert band.score_min <= borrower.credit_score <= band.score_max

    def test_all_bands_appear_in_a_large_sample(self) -> None:
        bands_seen = {borrower.score_band for borrower in generate_sample(seed=3)}
        assert bands_seen == set(SCORE_BAND_BY_NAME)

    def test_same_seed_means_identical_borrowers(self) -> None:
        assert generate_sample(seed=42) == generate_sample(seed=42)

    def test_different_seeds_mean_different_borrowers(self) -> None:
        assert generate_sample(seed=42) != generate_sample(seed=43)
