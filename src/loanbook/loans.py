"""Loan-term generation: amount, term, and score-band-priced APR per loan."""

from dataclasses import dataclass
from datetime import date
from math import log

import numpy as np

from loanbook.amortization import monthly_payment_cents
from loanbook.borrowers import Borrower
from loanbook.calibration import Calibration

PERSONAL_LOAN_PRODUCT_TYPE = "personal_loan"
RATE_DECIMAL_PLACES = 4


@dataclass(frozen=True)
class Loan:
    loan_id: str
    borrower_id: str
    product_type: str
    origination_month: date
    principal_cents: int
    term_months: int
    interest_rate: float
    monthly_payment_cents: int
    score_band: str


def generate_loan(
    loan_id: str,
    borrower: Borrower,
    origination_month: date,
    calibration: Calibration,
    rng: np.random.Generator,
) -> Loan:
    """Draw one loan's terms from the calibrated distributions."""
    principal_cents = _draw_principal_cents(calibration, rng)
    term_months = int(
        rng.choice(
            list(calibration.term_months_mix),
            p=list(calibration.term_months_mix.values()),
        )
    )
    interest_rate = _draw_interest_rate(borrower.score_band, calibration, rng)
    return Loan(
        loan_id=loan_id,
        borrower_id=borrower.borrower_id,
        product_type=PERSONAL_LOAN_PRODUCT_TYPE,
        origination_month=origination_month,
        principal_cents=principal_cents,
        term_months=term_months,
        interest_rate=interest_rate,
        monthly_payment_cents=monthly_payment_cents(principal_cents, interest_rate, term_months),
        score_band=borrower.score_band,
    )


def _draw_principal_cents(calibration: Calibration, rng: np.random.Generator) -> int:
    raw_cents = rng.lognormal(
        mean=log(calibration.loan_amount_log_median_cents),
        sigma=calibration.loan_amount_log_sigma,
    )
    rounded_cents = (
        round(raw_cents / calibration.loan_amount_rounding_cents)
        * calibration.loan_amount_rounding_cents
    )
    return min(
        max(rounded_cents, calibration.loan_amount_min_cents),
        calibration.loan_amount_max_cents,
    )


def _draw_interest_rate(
    score_band: str, calibration: Calibration, rng: np.random.Generator
) -> float:
    band_rate = calibration.annual_interest_rate_by_band[score_band]
    half_width = calibration.interest_rate_noise_half_width
    return round(band_rate + rng.uniform(-half_width, half_width), RATE_DECIMAL_PLACES)
