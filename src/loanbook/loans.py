"""Loan-term generation: amount, term, and score-band-priced APR per loan."""

from dataclasses import dataclass
from datetime import date
from math import log

import numpy as np

from loanbook.amortization import monthly_payment_cents
from loanbook.borrowers import Borrower
from loanbook.calibration import (
    AmortizingProductCalibration,
    Calibration,
    RevolvingProductCalibration,
)
from loanbook.products import ProductType, is_revolving

RATE_DECIMAL_PLACES = 4


@dataclass(frozen=True)
class Loan:
    """One credit account: an installment loan or a revolving card.

    Amortizing fields (principal, term, monthly payment) are None for cards;
    the revolving field (credit limit) is None for installment loans. The
    constructor rejects any other combination — a card with a term or a loan
    without a principal is a bug, not a row.
    """

    loan_id: str
    borrower_id: str
    product_type: str
    origination_month: date
    principal_cents: int | None
    term_months: int | None
    interest_rate: float
    monthly_payment_cents: int | None
    credit_limit_cents: int | None
    score_band: str

    def __post_init__(self) -> None:
        if is_revolving(ProductType(self.product_type)):
            self._validate_revolving_fields()
        else:
            self._validate_amortizing_fields()

    def _validate_amortizing_fields(self) -> None:
        if (
            self.principal_cents is None
            or self.term_months is None
            or self.monthly_payment_cents is None
        ):
            raise ValueError(
                f"{self.product_type} loan {self.loan_id} requires principal_cents, "
                "term_months, and monthly_payment_cents"
            )
        if self.credit_limit_cents is not None:
            raise ValueError(
                f"{self.product_type} loan {self.loan_id} must not carry a credit limit"
            )

    def _validate_revolving_fields(self) -> None:
        if self.credit_limit_cents is None:
            raise ValueError(f"credit card {self.loan_id} requires credit_limit_cents")
        if (
            self.principal_cents is not None
            or self.term_months is not None
            or self.monthly_payment_cents is not None
        ):
            raise ValueError(
                f"credit card {self.loan_id} must not carry principal, term, "
                "or monthly payment fields"
            )


def generate_loan(
    loan_id: str,
    borrower: Borrower,
    product_type: ProductType,
    origination_month: date,
    calibration: Calibration,
    rng: np.random.Generator,
) -> Loan:
    """Draw one account's terms from the product's calibrated distributions."""
    if is_revolving(product_type):
        return _generate_card_account(
            loan_id, borrower, origination_month, calibration.credit_card, rng
        )
    return _generate_amortizing_loan(
        loan_id,
        borrower,
        product_type,
        origination_month,
        calibration.amortizing_products[product_type],
        rng,
    )


def _generate_amortizing_loan(
    loan_id: str,
    borrower: Borrower,
    product_type: ProductType,
    origination_month: date,
    product: AmortizingProductCalibration,
    rng: np.random.Generator,
) -> Loan:
    principal_cents = _draw_principal_cents(product, rng)
    term_months = int(
        rng.choice(list(product.term_months_mix), p=list(product.term_months_mix.values()))
    )
    interest_rate = _draw_interest_rate(
        product.annual_interest_rate_by_band[borrower.score_band],
        product.interest_rate_noise_half_width,
        rng,
    )
    return Loan(
        loan_id=loan_id,
        borrower_id=borrower.borrower_id,
        product_type=product_type.value,
        origination_month=origination_month,
        principal_cents=principal_cents,
        term_months=term_months,
        interest_rate=interest_rate,
        monthly_payment_cents=monthly_payment_cents(principal_cents, interest_rate, term_months),
        credit_limit_cents=None,
        score_band=borrower.score_band,
    )


def _generate_card_account(
    loan_id: str,
    borrower: Borrower,
    origination_month: date,
    card: RevolvingProductCalibration,
    rng: np.random.Generator,
) -> Loan:
    interest_rate = _draw_interest_rate(
        card.annual_interest_rate_by_band[borrower.score_band],
        card.interest_rate_noise_half_width,
        rng,
    )
    return Loan(
        loan_id=loan_id,
        borrower_id=borrower.borrower_id,
        product_type=ProductType.CREDIT_CARD.value,
        origination_month=origination_month,
        principal_cents=None,
        term_months=None,
        interest_rate=interest_rate,
        monthly_payment_cents=None,
        credit_limit_cents=card.credit_limit_cents_by_band[borrower.score_band],
        score_band=borrower.score_band,
    )


def _draw_principal_cents(product: AmortizingProductCalibration, rng: np.random.Generator) -> int:
    raw_cents = rng.lognormal(
        mean=log(product.amount_log_median_cents),
        sigma=product.amount_log_sigma,
    )
    rounded_cents = round(raw_cents / product.amount_rounding_cents) * product.amount_rounding_cents
    return min(max(rounded_cents, product.amount_min_cents), product.amount_max_cents)


def _draw_interest_rate(
    band_rate: float, noise_half_width: float, rng: np.random.Generator
) -> float:
    return round(band_rate + rng.uniform(-noise_half_width, noise_half_width), RATE_DECIMAL_PLACES)
