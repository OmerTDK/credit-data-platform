"""Tests for loan-term generation and month arithmetic."""

from datetime import date

import numpy as np
import pytest

from loanbook.borrowers import generate_borrower
from loanbook.calibration import default_calibration
from loanbook.loans import Loan, generate_loan
from loanbook.months import add_months, parse_month

SAMPLE_SIZE = 500


class TestMonthArithmetic:
    def test_add_months_within_a_year(self) -> None:
        assert add_months(date(2022, 1, 1), 3) == date(2022, 4, 1)

    def test_add_months_across_year_boundary(self) -> None:
        assert add_months(date(2022, 11, 1), 3) == date(2023, 2, 1)

    def test_add_zero_months_is_identity(self) -> None:
        assert add_months(date(2022, 6, 1), 0) == date(2022, 6, 1)

    def test_parse_month(self) -> None:
        assert parse_month("2022-01") == date(2022, 1, 1)

    def test_parse_month_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            parse_month("January 2022")


def generate_sample(seed: int) -> list[Loan]:
    calibration = default_calibration()
    rng = np.random.default_rng(seed)
    loans = []
    for index in range(SAMPLE_SIZE):
        borrower = generate_borrower(f"B-{index:06d}", calibration, rng)
        loans.append(generate_loan(f"L-{index:06d}", borrower, date(2022, 3, 1), calibration, rng))
    return loans


class TestGenerateLoan:
    def test_loan_links_borrower_and_origination_month(self) -> None:
        loan = generate_sample(seed=1)[0]
        assert loan.loan_id == "L-000000"
        assert loan.borrower_id == "B-000000"
        assert loan.origination_month == date(2022, 3, 1)
        assert loan.product_type == "personal_loan"

    def test_amounts_stay_inside_marketplace_bounds(self) -> None:
        calibration = default_calibration()
        for loan in generate_sample(seed=2):
            assert (
                calibration.loan_amount_min_cents
                <= loan.principal_cents
                <= calibration.loan_amount_max_cents
            )

    def test_amounts_are_rounded_to_25_dollars(self) -> None:
        calibration = default_calibration()
        for loan in generate_sample(seed=3):
            assert loan.principal_cents % calibration.loan_amount_rounding_cents == 0

    def test_terms_come_from_the_calibrated_mix(self) -> None:
        terms_seen = {loan.term_months for loan in generate_sample(seed=4)}
        assert terms_seen == {36, 60}

    def test_rate_stays_within_band_noise_window(self) -> None:
        calibration = default_calibration()
        for loan in generate_sample(seed=5):
            band_rate = calibration.annual_interest_rate_by_band[loan.score_band]
            half_width = calibration.interest_rate_noise_half_width
            assert band_rate - half_width <= loan.interest_rate <= band_rate + half_width

    def test_monthly_payment_matches_annuity_formula(self) -> None:
        from loanbook.amortization import monthly_payment_cents

        for loan in generate_sample(seed=6)[:20]:
            assert loan.monthly_payment_cents == monthly_payment_cents(
                loan.principal_cents, loan.interest_rate, loan.term_months
            )

    def test_same_seed_means_identical_loans(self) -> None:
        assert generate_sample(seed=42) == generate_sample(seed=42)
