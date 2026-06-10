"""Whole-book generation: monthly origination cohorts simulated to an as-of date."""

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from loanbook.borrowers import Borrower, choose_weighted, generate_borrower
from loanbook.calibration import Calibration, default_calibration
from loanbook.loans import Loan, generate_loan
from loanbook.months import add_months
from loanbook.performance import MonthlyPerformance, simulate_loan_performance
from loanbook.products import ProductType

DEFAULT_SEED = 42
DEFAULT_COHORT_COUNT = 24
DEFAULT_LOANS_PER_COHORT = 500
DEFAULT_START_MONTH = date(2022, 1, 1)
DEFAULT_OBSERVATION_MONTHS_AFTER_LAST_COHORT = 12


def _default_as_of_month(start_month: date, cohort_count: int) -> date:
    last_cohort_month = add_months(start_month, cohort_count - 1)
    return add_months(last_cohort_month, DEFAULT_OBSERVATION_MONTHS_AFTER_LAST_COHORT)


@dataclass(frozen=True)
class GeneratorConfig:
    """Book dimensions and observation cutoff.

    Contract: as_of_month must be on or after the last cohort month, so every
    configured cohort exists by the as-of date. A config whose as_of_month
    falls inside the cohort span is rejected rather than silently truncating
    cohorts. Loans originated in the as-of month itself have no closed
    reporting period yet, so they carry no performance rows.
    """

    seed: int
    cohort_count: int = DEFAULT_COHORT_COUNT
    loans_per_cohort: int = DEFAULT_LOANS_PER_COHORT
    start_month: date = DEFAULT_START_MONTH
    as_of_month: date | None = None

    def __post_init__(self) -> None:
        if self.cohort_count <= 0:
            raise ValueError(f"cohort_count must be positive, got {self.cohort_count}")
        if self.loans_per_cohort <= 0:
            raise ValueError(f"loans_per_cohort must be positive, got {self.loans_per_cohort}")
        if self.as_of_month is None:
            object.__setattr__(
                self, "as_of_month", _default_as_of_month(self.start_month, self.cohort_count)
            )
        last_cohort_month = add_months(self.start_month, self.cohort_count - 1)
        if self.as_of_month < last_cohort_month:
            raise ValueError(
                f"as_of_month {self.as_of_month} is inside the cohort span: the last of "
                f"{self.cohort_count} cohorts originates {last_cohort_month}. as_of_month "
                f"must be on or after the last cohort month."
            )


@dataclass(frozen=True)
class LoanBook:
    borrowers: list[Borrower] = field(default_factory=list)
    loans: list[Loan] = field(default_factory=list)
    monthly_performance: list[MonthlyPerformance] = field(default_factory=list)


def generate_loan_book(config: GeneratorConfig, calibration: Calibration | None = None) -> LoanBook:
    """Generate borrowers, accounts, and monthly performance for the whole book.

    Each account's product is drawn from the calibration's product mix, so the
    book is card-heavy by count and mortgage-heavy by balance like the consumer
    credit composition it is calibrated against. A single seeded generator
    drives every draw in a fixed iteration order, so the same config always
    produces an identical book.
    """
    if calibration is None:
        calibration = default_calibration()
    rng = np.random.default_rng(config.seed)
    book = LoanBook()
    entity_index = 0
    for cohort_index in range(config.cohort_count):
        origination_month = add_months(config.start_month, cohort_index)
        for _ in range(config.loans_per_cohort):
            borrower = generate_borrower(f"B-{entity_index:06d}", calibration, rng)
            product_type = ProductType(choose_weighted(rng, calibration.product_mix))
            loan = generate_loan(
                f"L-{entity_index:06d}",
                borrower,
                product_type,
                origination_month,
                calibration,
                rng,
            )
            performance_rows = simulate_loan_performance(loan, config.as_of_month, calibration, rng)
            book.borrowers.append(borrower)
            book.loans.append(loan)
            book.monthly_performance.extend(performance_rows)
            entity_index += 1
    return book
