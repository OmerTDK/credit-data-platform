"""Borrower attribute generation from the calibrated categorical mixes."""

from dataclasses import dataclass

import numpy as np

from loanbook.calibration import SCORE_BAND_BY_NAME, Calibration


@dataclass(frozen=True)
class Borrower:
    borrower_id: str
    age_band: str
    income_band: str
    region: str
    score_band: str
    credit_score: int


def choose_weighted(rng: np.random.Generator, weights_by_category: dict[str, float]) -> str:
    """Draw one category according to its probability weight.

    Args:
        rng: Seeded random generator driving the draw.
        weights_by_category: Mapping of category name to probability; the
            probabilities must sum to 1.

    Returns:
        The drawn category name.
    """
    categories = list(weights_by_category)
    probabilities = list(weights_by_category.values())
    return str(rng.choice(categories, p=probabilities))


def generate_borrower(
    borrower_id: str, calibration: Calibration, rng: np.random.Generator
) -> Borrower:
    """Draw one borrower's attributes from the calibrated distributions.

    The score band is drawn from the origination mix, then the credit score
    is drawn uniformly within that band's score range; the demographic
    attributes are drawn independently from their categorical mixes.

    Args:
        borrower_id: Unique identifier to assign to the borrower.
        calibration: Source of the categorical mixes and score bands.
        rng: Seeded random generator driving every draw.

    Returns:
        A fully populated immutable Borrower.
    """
    score_band_name = choose_weighted(rng, calibration.origination_mix_by_band)
    score_band = SCORE_BAND_BY_NAME[score_band_name]
    credit_score = int(rng.integers(score_band.score_min, score_band.score_max, endpoint=True))
    return Borrower(
        borrower_id=borrower_id,
        age_band=choose_weighted(rng, calibration.age_band_mix),
        income_band=choose_weighted(rng, calibration.income_band_mix),
        region=choose_weighted(rng, calibration.region_mix),
        score_band=score_band_name,
        credit_score=credit_score,
    )
