"""Monthly loan performance simulation driven by the delinquency state machine.

Arrears are modeled as whole missed installments: due installments accrue one
per month until maturity, and the gap between due and paid installments maps
to the delinquency bucket. Every emitted transition is validated against the
legal-transition table, so an illegal move is a crash, not a data point.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np

from loanbook.amortization import AmortizationEntry, build_amortization_schedule
from loanbook.calibration import Calibration
from loanbook.loans import Loan
from loanbook.months import add_months
from loanbook.state_machine import (
    MISSED_PAYMENTS_FOR_DEFAULT,
    TERMINAL_STATUSES,
    DelinquencyBucket,
    LoanStatus,
    bucket_for_missed_payments,
    validate_bucket_transition,
)

DELINQUENT_OUTCOMES = ("cure", "stay", "roll_deeper")


@dataclass(frozen=True)
class MonthlyPerformance:
    loan_id: str
    period: int
    report_month: date
    beginning_balance_cents: int
    scheduled_payment_cents: int
    actual_payment_cents: int
    principal_paid_cents: int
    interest_paid_cents: int
    ending_balance_cents: int
    principal_writeoff_cents: int
    recovery_cents: int
    delinquency_bucket: DelinquencyBucket
    loan_status: LoanStatus
    is_prepayment: bool


def simulate_loan_performance(
    loan: Loan,
    as_of_month: date,
    calibration: Calibration,
    rng: np.random.Generator,
) -> list[MonthlyPerformance]:
    """Simulate one loan month by month until termination or the as-of cutoff."""
    return _LoanSimulator(loan, calibration, rng).run(as_of_month)


class _LoanSimulator:
    def __init__(self, loan: Loan, calibration: Calibration, rng: np.random.Generator) -> None:
        self.loan = loan
        self.calibration = calibration
        self.rng = rng
        self.schedule = build_amortization_schedule(
            loan.principal_cents, loan.interest_rate, loan.term_months
        )
        self.installments_paid = 0
        self.bucket = DelinquencyBucket.CURRENT
        self.status = LoanStatus.ACTIVE
        self.default_period = 0
        self.writeoff_cents = 0

    def run(self, as_of_month: date) -> list[MonthlyPerformance]:
        rows: list[MonthlyPerformance] = []
        period = 1
        while add_months(self.loan.origination_month, period) <= as_of_month:
            if self.status == LoanStatus.ACTIVE:
                row = self._step_active_month(period)
            else:
                row = self._step_defaulted_month(period)
            rows.append(row)
            if row.loan_status in TERMINAL_STATUSES:
                break
            period += 1
        return rows

    def _step_active_month(self, period: int) -> MonthlyPerformance:
        due_now = min(period, self.loan.term_months)
        newly_due = due_now - min(period - 1, self.loan.term_months)
        arrears_before = due_now - newly_due - self.installments_paid
        is_current = arrears_before == 0

        if is_current and self._draws_prepayment():
            return self._emit_prepayment(period, due_now, newly_due)
        installments_to_pay = (
            self._current_installments_to_pay(newly_due)
            if is_current
            else self._delinquent_installments_to_pay(arrears_before, newly_due)
        )
        return self._emit_payment_outcome(period, due_now, newly_due, installments_to_pay)

    def _draws_prepayment(self) -> bool:
        smm = self.calibration.monthly_prepayment_rate_by_band[self.loan.score_band]
        return self.rng.random() < smm

    def _current_installments_to_pay(self, newly_due: int) -> int:
        hazard = self.calibration.monthly_delinquency_entry_hazard_by_band[self.loan.score_band]
        if self.rng.random() < hazard:
            return 0
        return newly_due

    def _delinquent_installments_to_pay(self, arrears_before: int, newly_due: int) -> int:
        outcomes = self.calibration.delinquent_roll_probabilities[self.bucket.value]
        outcome = str(
            self.rng.choice(
                DELINQUENT_OUTCOMES,
                p=[outcomes[name] for name in DELINQUENT_OUTCOMES],
            )
        )
        if outcome == "cure":
            return arrears_before + newly_due
        if outcome == "stay":
            return newly_due
        return 0

    def _emit_prepayment(self, period: int, due_now: int, newly_due: int) -> MonthlyPerformance:
        beginning_balance = self._open_balance_cents()
        interest_cents = self.schedule[self.installments_paid].interest_cents
        self.installments_paid = self.loan.term_months
        self.status = LoanStatus.PAID_OFF
        self._transition_to(DelinquencyBucket.CURRENT)
        return MonthlyPerformance(
            loan_id=self.loan.loan_id,
            period=period,
            report_month=add_months(self.loan.origination_month, period),
            beginning_balance_cents=beginning_balance,
            scheduled_payment_cents=self._scheduled_payment_cents(due_now, newly_due),
            actual_payment_cents=beginning_balance + interest_cents,
            principal_paid_cents=beginning_balance,
            interest_paid_cents=interest_cents,
            ending_balance_cents=0,
            principal_writeoff_cents=0,
            recovery_cents=0,
            delinquency_bucket=self.bucket,
            loan_status=self.status,
            is_prepayment=True,
        )

    def _emit_payment_outcome(
        self, period: int, due_now: int, newly_due: int, installments_to_pay: int
    ) -> MonthlyPerformance:
        beginning_balance = self._open_balance_cents()
        paid_entries = self.schedule[
            self.installments_paid : self.installments_paid + installments_to_pay
        ]
        self.installments_paid += installments_to_pay
        arrears_after = due_now - self.installments_paid

        if arrears_after >= MISSED_PAYMENTS_FOR_DEFAULT:
            return self._emit_default(period, due_now, newly_due, beginning_balance)

        self._transition_to(bucket_for_missed_payments(arrears_after))
        if self.installments_paid == self.loan.term_months:
            self.status = LoanStatus.PAID_OFF
        principal_paid = sum(entry.principal_cents for entry in paid_entries)
        interest_paid = sum(entry.interest_cents for entry in paid_entries)
        return MonthlyPerformance(
            loan_id=self.loan.loan_id,
            period=period,
            report_month=add_months(self.loan.origination_month, period),
            beginning_balance_cents=beginning_balance,
            scheduled_payment_cents=self._scheduled_payment_cents(due_now, newly_due),
            actual_payment_cents=principal_paid + interest_paid,
            principal_paid_cents=principal_paid,
            interest_paid_cents=interest_paid,
            ending_balance_cents=self._open_balance_cents(),
            principal_writeoff_cents=0,
            recovery_cents=0,
            delinquency_bucket=self.bucket,
            loan_status=self.status,
            is_prepayment=False,
        )

    def _emit_default(
        self, period: int, due_now: int, newly_due: int, beginning_balance: int
    ) -> MonthlyPerformance:
        self._transition_to(DelinquencyBucket.DEFAULT)
        self.status = LoanStatus.DEFAULTED
        self.default_period = period
        self.writeoff_cents = beginning_balance
        return MonthlyPerformance(
            loan_id=self.loan.loan_id,
            period=period,
            report_month=add_months(self.loan.origination_month, period),
            beginning_balance_cents=beginning_balance,
            scheduled_payment_cents=self._scheduled_payment_cents(due_now, newly_due),
            actual_payment_cents=0,
            principal_paid_cents=0,
            interest_paid_cents=0,
            ending_balance_cents=0,
            principal_writeoff_cents=beginning_balance,
            recovery_cents=0,
            delinquency_bucket=self.bucket,
            loan_status=self.status,
            is_prepayment=False,
        )

    def _step_defaulted_month(self, period: int) -> MonthlyPerformance:
        months_since_default = period - self.default_period
        is_recovery_month = months_since_default == self.calibration.recovery_lag_months
        recovery_cents = 0
        if is_recovery_month:
            recovery_cents = round(
                self.writeoff_cents * self.calibration.recovery_rate_on_defaulted_balance
            )
            self.status = LoanStatus.RECOVERY_COMPLETE
        self._transition_to(DelinquencyBucket.DEFAULT)
        return MonthlyPerformance(
            loan_id=self.loan.loan_id,
            period=period,
            report_month=add_months(self.loan.origination_month, period),
            beginning_balance_cents=0,
            scheduled_payment_cents=0,
            actual_payment_cents=0,
            principal_paid_cents=0,
            interest_paid_cents=0,
            ending_balance_cents=0,
            principal_writeoff_cents=0,
            recovery_cents=recovery_cents,
            delinquency_bucket=self.bucket,
            loan_status=self.status,
            is_prepayment=False,
        )

    def _transition_to(self, next_bucket: DelinquencyBucket) -> None:
        validate_bucket_transition(self.bucket, next_bucket)
        self.bucket = next_bucket

    def _open_balance_cents(self) -> int:
        if self.installments_paid == 0:
            return self.loan.principal_cents
        return self.schedule[self.installments_paid - 1].ending_balance_cents

    def _scheduled_payment_cents(self, due_now: int, newly_due: int) -> int:
        if newly_due == 0:
            return 0
        entry: AmortizationEntry = self.schedule[due_now - 1]
        return entry.payment_cents
