"""Monthly revolving-card simulation: draws, minimums, and 180-day charge-off.

The simplified revolving model (ADR-0004): each current month the borrower
draws spend toward the band's target utilization (capped at the limit), then
either misses the minimum, pays the statement in full (grace period, no
interest), or revolves paying exactly the minimum — interest plus 1% of the
statement balance with a dollar floor. Interest accrues on the carried balance
and capitalizes when unpaid. Delinquent accounts are suspended (no draws) and
resolve through the shared cure/stay/roll-deeper machinery; six missed
minimums (180 days past due, FFIEC open-end rule) charge off the full balance,
followed by the same lagged-recovery flow as installment loans. Cards have no
maturity: an account that never charges off emits a row every month through
the as-of cutoff.
"""

from datetime import date

import numpy as np

from loanbook.calibration import RevolvingProductCalibration
from loanbook.loans import Loan
from loanbook.months import MONTHS_PER_YEAR, add_months
from loanbook.performance import DELINQUENT_OUTCOMES, MonthlyPerformance
from loanbook.state_machine import (
    MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING,
    TERMINAL_STATUSES,
    DelinquencyBucket,
    LoanStatus,
    bucket_for_missed_payments,
    validate_bucket_transition,
)

UTILIZATION_DECIMAL_PLACES = 6


def simulate_card_performance(
    loan: Loan,
    as_of_month: date,
    card: RevolvingProductCalibration,
    rng: np.random.Generator,
) -> list[MonthlyPerformance]:
    """Simulate one card account month by month until charge-off resolution or as-of."""
    return _CardSimulator(loan, card, rng).run(as_of_month)


class _CardSimulator:
    def __init__(
        self, loan: Loan, card: RevolvingProductCalibration, rng: np.random.Generator
    ) -> None:
        self.loan = loan
        self.card = card
        self.rng = rng
        self.monthly_rate = loan.interest_rate / MONTHS_PER_YEAR
        self.target_balance_cents = round(
            card.target_utilization_by_band[loan.score_band] * loan.credit_limit_cents
        )
        self.balance_cents = 0
        self.missed_minimums = 0
        self.arrears_minimum_cents = 0
        self.bucket = DelinquencyBucket.CURRENT
        self.status = LoanStatus.ACTIVE
        self.charge_off_period = 0
        self.writeoff_cents = 0

    def run(self, as_of_month: date) -> list[MonthlyPerformance]:
        rows: list[MonthlyPerformance] = []
        period = 1
        while add_months(self.loan.origination_month, period) <= as_of_month:
            if self.status == LoanStatus.ACTIVE:
                row = self._step_active_month(period)
            else:
                row = self._step_charged_off_month(period)
            rows.append(row)
            if row.loan_status in TERMINAL_STATUSES:
                break
            period += 1
        return rows

    def _step_active_month(self, period: int) -> MonthlyPerformance:
        if self.missed_minimums == 0:
            return self._step_current_month(period)
        return self._step_delinquent_month(period)

    def _step_current_month(self, period: int) -> MonthlyPerformance:
        beginning_balance = self.balance_cents
        draw = self._draw_spend(beginning_balance)
        misses_minimum = (
            self.rng.random()
            < (self.card.monthly_delinquency_entry_hazard_by_band[self.loan.score_band])
        )
        if misses_minimum:
            return self._emit_missed_minimum(period, beginning_balance, draw)
        pays_in_full = (
            self.rng.random() < (self.card.pay_in_full_probability_by_band[self.loan.score_band])
        )
        if pays_in_full:
            return self._emit_paid_in_full(period, beginning_balance, draw)
        return self._emit_revolving_minimum(period, beginning_balance, draw)

    def _draw_spend(self, beginning_balance: int) -> int:
        replenishment = self.rng.uniform(
            self.card.spend_replenishment_min, self.card.spend_replenishment_max
        )
        intended = round(max(self.target_balance_cents - beginning_balance, 0) * replenishment)
        # Headroom can be negative right after a cure, while capitalized
        # delinquent interest still holds the balance over the limit.
        headroom = max(self.loan.credit_limit_cents - beginning_balance, 0)
        return min(intended, headroom)

    def _interest_on_carried_balance(self, beginning_balance: int) -> int:
        return round(beginning_balance * self.monthly_rate)

    def _minimum_due(self, interest_charged: int, statement_balance: int) -> int:
        formula = interest_charged + round(
            self.card.minimum_payment_principal_rate * statement_balance
        )
        return min(max(formula, self.card.minimum_payment_floor_cents), statement_balance)

    def _emit_missed_minimum(
        self, period: int, beginning_balance: int, draw: int
    ) -> MonthlyPerformance:
        interest_charged = self._interest_on_carried_balance(beginning_balance)
        statement_balance = beginning_balance + draw + interest_charged
        minimum_due = self._minimum_due(interest_charged, statement_balance)
        self.missed_minimums = 1
        self.arrears_minimum_cents = minimum_due
        self._transition_to_missed_bucket()
        self.balance_cents = statement_balance
        return self._emit_row(
            period, beginning_balance, draw, interest_charged, minimum_due, payment=0
        )

    def _emit_paid_in_full(
        self, period: int, beginning_balance: int, draw: int
    ) -> MonthlyPerformance:
        statement_balance = beginning_balance + draw
        minimum_due = self._minimum_due(0, statement_balance)
        self._transition_to(DelinquencyBucket.CURRENT)
        self.balance_cents = 0
        return self._emit_row(
            period, beginning_balance, draw, 0, minimum_due, payment=statement_balance
        )

    def _emit_revolving_minimum(
        self, period: int, beginning_balance: int, draw: int
    ) -> MonthlyPerformance:
        interest_charged = self._interest_on_carried_balance(beginning_balance)
        statement_balance = beginning_balance + draw + interest_charged
        minimum_due = self._minimum_due(interest_charged, statement_balance)
        self._transition_to(DelinquencyBucket.CURRENT)
        self.balance_cents = statement_balance - minimum_due
        return self._emit_row(
            period, beginning_balance, draw, interest_charged, minimum_due, payment=minimum_due
        )

    def _step_delinquent_month(self, period: int) -> MonthlyPerformance:
        outcomes = self.card.delinquent_roll_probabilities[self.bucket.value]
        outcome = str(
            self.rng.choice(DELINQUENT_OUTCOMES, p=[outcomes[name] for name in DELINQUENT_OUTCOMES])
        )
        rolls_to_charge_off = (
            outcome == "roll_deeper"
            and self.missed_minimums + 1 == MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING
        )
        if rolls_to_charge_off:
            return self._emit_charge_off(period)

        beginning_balance = self.balance_cents
        interest_charged = self._interest_on_carried_balance(beginning_balance)
        statement_balance = beginning_balance + interest_charged
        minimum_due = self._minimum_due(interest_charged, statement_balance)
        payment = self._delinquent_payment(outcome, minimum_due, statement_balance)
        self._transition_to_missed_bucket()
        self.balance_cents = statement_balance - payment
        return self._emit_row(period, beginning_balance, 0, interest_charged, minimum_due, payment)

    def _delinquent_payment(self, outcome: str, minimum_due: int, statement_balance: int) -> int:
        if outcome == "cure":
            payment = min(self.arrears_minimum_cents + minimum_due, statement_balance)
            self.missed_minimums = 0
            self.arrears_minimum_cents = 0
            return payment
        if outcome == "stay":
            return minimum_due
        self.arrears_minimum_cents += minimum_due
        self.missed_minimums += 1
        return 0

    def _emit_charge_off(self, period: int) -> MonthlyPerformance:
        beginning_balance = self.balance_cents
        self.missed_minimums = MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING
        self._transition_to_missed_bucket()
        self.status = LoanStatus.DEFAULTED
        self.charge_off_period = period
        self.writeoff_cents = beginning_balance
        self.balance_cents = 0
        return self._emit_row(
            period,
            beginning_balance,
            0,
            0,
            minimum_due=0,
            payment=0,
            principal_writeoff_cents=beginning_balance,
        )

    def _step_charged_off_month(self, period: int) -> MonthlyPerformance:
        months_since_charge_off = period - self.charge_off_period
        recovery_cents = 0
        if months_since_charge_off == self.card.recovery_lag_months:
            recovery_cents = round(
                self.writeoff_cents * self.card.recovery_rate_on_charged_off_balance
            )
            self.status = LoanStatus.RECOVERY_COMPLETE
        self._transition_to(DelinquencyBucket.DEFAULT)
        return self._emit_row(
            period, 0, 0, 0, minimum_due=0, payment=0, recovery_cents=recovery_cents
        )

    def _transition_to_missed_bucket(self) -> None:
        self._transition_to(
            bucket_for_missed_payments(
                self.missed_minimums,
                missed_payments_for_default=MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING,
            )
        )

    def _transition_to(self, next_bucket: DelinquencyBucket) -> None:
        validate_bucket_transition(self.bucket, next_bucket)
        self.bucket = next_bucket

    def _emit_row(
        self,
        period: int,
        beginning_balance: int,
        draw: int,
        interest_charged: int,
        minimum_due: int,
        payment: int,
        principal_writeoff_cents: int = 0,
        recovery_cents: int = 0,
    ) -> MonthlyPerformance:
        interest_paid = min(payment, interest_charged)
        return MonthlyPerformance(
            loan_id=self.loan.loan_id,
            product_type=self.loan.product_type,
            period=period,
            report_month=add_months(self.loan.origination_month, period),
            beginning_balance_cents=beginning_balance,
            draw_cents=draw,
            scheduled_payment_cents=minimum_due,
            actual_payment_cents=payment,
            principal_paid_cents=payment - interest_paid,
            interest_paid_cents=interest_paid,
            interest_charged_cents=interest_charged,
            ending_balance_cents=self.balance_cents,
            principal_writeoff_cents=principal_writeoff_cents,
            recovery_cents=recovery_cents,
            utilization_rate=round(
                self.balance_cents / self.loan.credit_limit_cents, UTILIZATION_DECIMAL_PLACES
            ),
            delinquency_bucket=self.bucket,
            loan_status=self.status,
            is_prepayment=False,
        )
