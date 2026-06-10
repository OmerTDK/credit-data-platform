"""Cent-exact annuity amortization so balance invariants hold without float drift."""

from dataclasses import dataclass

MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class AmortizationEntry:
    period: int
    payment_cents: int
    interest_cents: int
    principal_cents: int
    ending_balance_cents: int


def monthly_payment_cents(principal_cents: int, annual_rate: float, term_months: int) -> int:
    """Standard annuity payment, rounded to whole cents.

    Args:
        principal_cents: Loan principal in cents, must be positive.
        annual_rate: Nominal annual interest rate as a decimal (0.12 = 12% APR).
        term_months: Number of monthly installments, must be positive.

    Returns:
        The level monthly payment in cents.

    Raises:
        ValueError: If any input is non-positive.
    """
    _validate_loan_terms(principal_cents, annual_rate, term_months)
    monthly_rate = annual_rate / MONTHS_PER_YEAR
    annuity_factor = monthly_rate / (1 - (1 + monthly_rate) ** -term_months)
    return round(principal_cents * annuity_factor)


def build_amortization_schedule(
    principal_cents: int, annual_rate: float, term_months: int
) -> list[AmortizationEntry]:
    """Build the full installment schedule with exact cent accounting.

    Interest each period is the monthly rate applied to the open balance,
    rounded to cents; principal is the remainder of the level payment. The
    final installment clears the residual balance exactly, so principal
    portions always sum to the original principal.
    """
    _validate_loan_terms(principal_cents, annual_rate, term_months)
    payment_cents = monthly_payment_cents(principal_cents, annual_rate, term_months)
    monthly_rate = annual_rate / MONTHS_PER_YEAR

    schedule: list[AmortizationEntry] = []
    open_balance_cents = principal_cents
    for period in range(1, term_months + 1):
        interest_cents = round(open_balance_cents * monthly_rate)
        is_final_period = period == term_months
        if is_final_period:
            principal_portion_cents = open_balance_cents
        else:
            principal_portion_cents = min(payment_cents - interest_cents, open_balance_cents)
        ending_balance_cents = open_balance_cents - principal_portion_cents
        schedule.append(
            AmortizationEntry(
                period=period,
                payment_cents=interest_cents + principal_portion_cents,
                interest_cents=interest_cents,
                principal_cents=principal_portion_cents,
                ending_balance_cents=ending_balance_cents,
            )
        )
        open_balance_cents = ending_balance_cents
    return schedule


def _validate_loan_terms(principal_cents: int, annual_rate: float, term_months: int) -> None:
    if principal_cents <= 0:
        raise ValueError(f"principal_cents must be positive, got {principal_cents}")
    if annual_rate <= 0:
        raise ValueError(f"annual_rate must be positive, got {annual_rate}")
    if term_months <= 0:
        raise ValueError(f"term_months must be positive, got {term_months}")
