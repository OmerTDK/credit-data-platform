"""Tests for per-product loan-term generation and month arithmetic."""

from datetime import date

import numpy as np
import pytest

from loanbook.amortization import monthly_payment_cents
from loanbook.borrowers import generate_borrower
from loanbook.calibration import default_calibration
from loanbook.loans import Loan, generate_loan
from loanbook.months import add_months, parse_month
from loanbook.products import AMORTIZING_PRODUCT_TYPES, ProductType

SAMPLE_SIZE = 500
ORIGINATION_MONTH = date(2022, 3, 1)


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


def generate_sample(seed: int, product_type: ProductType) -> list[Loan]:
    calibration = default_calibration()
    rng = np.random.default_rng(seed)
    loans = []
    for index in range(SAMPLE_SIZE):
        borrower = generate_borrower(f"B-{index:06d}", calibration, rng)
        loans.append(
            generate_loan(
                f"L-{index:06d}", borrower, product_type, ORIGINATION_MONTH, calibration, rng
            )
        )
    return loans


class TestGenerateAmortizingLoan:
    @pytest.fixture(scope="class", params=sorted(AMORTIZING_PRODUCT_TYPES))
    def product_and_sample(self, request: pytest.FixtureRequest) -> tuple[str, list[Loan]]:
        return request.param, generate_sample(seed=2, product_type=ProductType(request.param))

    def test_loan_links_borrower_product_and_origination_month(
        self, product_and_sample: tuple[str, list[Loan]]
    ) -> None:
        product_type, sample = product_and_sample
        loan = sample[0]
        assert loan.loan_id == "L-000000"
        assert loan.borrower_id == "B-000000"
        assert loan.origination_month == ORIGINATION_MONTH
        assert loan.product_type == product_type

    def test_amortizing_loans_carry_no_credit_limit(
        self, product_and_sample: tuple[str, list[Loan]]
    ) -> None:
        _, sample = product_and_sample
        assert all(loan.credit_limit_cents is None for loan in sample)

    def test_amounts_stay_inside_the_product_bounds(
        self, product_and_sample: tuple[str, list[Loan]]
    ) -> None:
        product_type, sample = product_and_sample
        product = default_calibration().amortizing_products[product_type]
        for loan in sample:
            assert product.amount_min_cents <= loan.principal_cents <= product.amount_max_cents

    def test_amounts_are_rounded_to_the_product_increment(
        self, product_and_sample: tuple[str, list[Loan]]
    ) -> None:
        product_type, sample = product_and_sample
        product = default_calibration().amortizing_products[product_type]
        assert all(loan.principal_cents % product.amount_rounding_cents == 0 for loan in sample)

    def test_terms_come_from_the_product_term_mix(
        self, product_and_sample: tuple[str, list[Loan]]
    ) -> None:
        product_type, sample = product_and_sample
        product = default_calibration().amortizing_products[product_type]
        assert {loan.term_months for loan in sample} == set(product.term_months_mix)

    def test_rate_stays_within_the_product_band_noise_window(
        self, product_and_sample: tuple[str, list[Loan]]
    ) -> None:
        product_type, sample = product_and_sample
        product = default_calibration().amortizing_products[product_type]
        for loan in sample:
            band_rate = product.annual_interest_rate_by_band[loan.score_band]
            half_width = product.interest_rate_noise_half_width
            assert band_rate - half_width <= loan.interest_rate <= band_rate + half_width

    def test_monthly_payment_matches_annuity_formula(
        self, product_and_sample: tuple[str, list[Loan]]
    ) -> None:
        _, sample = product_and_sample
        for loan in sample[:20]:
            assert loan.monthly_payment_cents == monthly_payment_cents(
                loan.principal_cents, loan.interest_rate, loan.term_months
            )


class TestGenerateCardAccount:
    @pytest.fixture(scope="class")
    def sample(self) -> list[Loan]:
        return generate_sample(seed=3, product_type=ProductType.CREDIT_CARD)

    def test_card_carries_the_band_credit_limit(self, sample: list[Loan]) -> None:
        card = default_calibration().credit_card
        for account in sample:
            assert account.credit_limit_cents == card.credit_limit_cents_by_band[account.score_band]

    def test_card_has_no_amortizing_fields(self, sample: list[Loan]) -> None:
        for account in sample:
            assert account.principal_cents is None
            assert account.term_months is None
            assert account.monthly_payment_cents is None

    def test_card_rate_stays_within_the_band_noise_window(self, sample: list[Loan]) -> None:
        card = default_calibration().credit_card
        for account in sample:
            band_rate = card.annual_interest_rate_by_band[account.score_band]
            half_width = card.interest_rate_noise_half_width
            assert band_rate - half_width <= account.interest_rate <= band_rate + half_width


class TestLoanFieldValidation:
    def amortizing_loan_fields(self) -> dict:
        return {
            "loan_id": "L-000000",
            "borrower_id": "B-000000",
            "product_type": ProductType.AUTO_LOAN.value,
            "origination_month": ORIGINATION_MONTH,
            "principal_cents": 2_000_000,
            "term_months": 60,
            "interest_rate": 0.09,
            "monthly_payment_cents": monthly_payment_cents(2_000_000, 0.09, 60),
            "credit_limit_cents": None,
            "score_band": "prime",
        }

    def test_amortizing_loan_without_a_term_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="term_months"):
            Loan(**{**self.amortizing_loan_fields(), "term_months": None})

    def test_amortizing_loan_with_a_credit_limit_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="credit limit"):
            Loan(**{**self.amortizing_loan_fields(), "credit_limit_cents": 500_000})

    def test_card_without_a_credit_limit_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="credit_limit_cents"):
            Loan(
                **{
                    **self.amortizing_loan_fields(),
                    "product_type": ProductType.CREDIT_CARD.value,
                    "principal_cents": None,
                    "term_months": None,
                    "monthly_payment_cents": None,
                }
            )

    def test_card_with_amortizing_fields_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not carry principal"):
            Loan(
                **{
                    **self.amortizing_loan_fields(),
                    "product_type": ProductType.CREDIT_CARD.value,
                    "credit_limit_cents": 500_000,
                }
            )


class TestReproducibility:
    def test_same_seed_means_identical_loans(self) -> None:
        for product_type in ProductType:
            first = generate_sample(seed=42, product_type=product_type)
            second = generate_sample(seed=42, product_type=product_type)
            assert first == second
