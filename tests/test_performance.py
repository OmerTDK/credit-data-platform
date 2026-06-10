"""Property-style tests for the monthly performance simulator.

The invariants here are the product: they hold for every loan in a
fixed-seed population large enough to exercise prepayment, every delinquency
bucket, cure, default, and the recovery flow.
"""

from datetime import date
from itertools import pairwise

import numpy as np
import pytest

from loanbook.borrowers import generate_borrower
from loanbook.calibration import default_calibration
from loanbook.loans import Loan, generate_loan
from loanbook.performance import MonthlyPerformance, simulate_loan_performance
from loanbook.state_machine import (
    TERMINAL_STATUSES,
    DelinquencyBucket,
    LoanStatus,
    validate_bucket_transition,
)

POPULATION_SIZE = 2_000
POPULATION_SEED = 42
ORIGINATION_MONTH = date(2020, 1, 1)
AS_OF_MONTH = date(2026, 1, 1)


@pytest.fixture(scope="module")
def population() -> list[tuple[Loan, list[MonthlyPerformance]]]:
    calibration = default_calibration()
    rng = np.random.default_rng(POPULATION_SEED)
    simulated = []
    for index in range(POPULATION_SIZE):
        borrower = generate_borrower(f"B-{index:06d}", calibration, rng)
        loan = generate_loan(f"L-{index:06d}", borrower, ORIGINATION_MONTH, calibration, rng)
        rows = simulate_loan_performance(loan, AS_OF_MONTH, calibration, rng)
        simulated.append((loan, rows))
    return simulated


class TestRowShape:
    def test_every_loan_has_rows(self, population) -> None:
        assert all(rows for _, rows in population)

    def test_periods_are_contiguous_from_one(self, population) -> None:
        for _, rows in population:
            assert [row.period for row in rows] == list(range(1, len(rows) + 1))

    def test_report_months_start_one_month_after_origination(self, population) -> None:
        for _, rows in population:
            assert rows[0].report_month == date(2020, 2, 1)

    def test_no_report_month_beyond_as_of(self, population) -> None:
        for _, rows in population:
            assert all(row.report_month <= AS_OF_MONTH for row in rows)


class TestTerminalStates:
    def test_no_rows_after_a_terminal_status(self, population) -> None:
        for _, rows in population:
            for row in rows[:-1]:
                assert row.loan_status not in TERMINAL_STATUSES

    def test_population_exercises_every_terminal_path(self, population) -> None:
        final_statuses = {rows[-1].loan_status for _, rows in population}
        assert LoanStatus.PAID_OFF in final_statuses
        assert LoanStatus.RECOVERY_COMPLETE in final_statuses

    def test_population_exercises_prepayment_and_every_bucket(self, population) -> None:
        all_rows = [row for _, rows in population for row in rows]
        assert any(row.is_prepayment for row in all_rows)
        buckets_seen = {row.delinquency_bucket for row in all_rows}
        assert buckets_seen == set(DelinquencyBucket)


class TestBucketTransitions:
    def test_every_consecutive_transition_is_legal(self, population) -> None:
        for _, rows in population:
            for earlier, later in pairwise(rows):
                validate_bucket_transition(earlier.delinquency_bucket, later.delinquency_bucket)

    def test_first_row_starts_current_or_one_bucket_deep(self, population) -> None:
        for _, rows in population:
            assert rows[0].delinquency_bucket in {
                DelinquencyBucket.CURRENT,
                DelinquencyBucket.DPD_30,
            }


class TestBalanceIntegrity:
    def test_balances_are_never_negative(self, population) -> None:
        for _, rows in population:
            for row in rows:
                assert row.beginning_balance_cents >= 0
                assert row.ending_balance_cents >= 0

    def test_each_row_conserves_principal(self, population) -> None:
        for _, rows in population:
            for row in rows:
                assert (
                    row.ending_balance_cents
                    == row.beginning_balance_cents
                    - row.principal_paid_cents
                    - row.principal_writeoff_cents
                )

    def test_principal_paid_plus_writeoff_plus_open_balance_equals_originated(
        self, population
    ) -> None:
        for loan, rows in population:
            principal_paid = sum(row.principal_paid_cents for row in rows)
            written_off = sum(row.principal_writeoff_cents for row in rows)
            assert principal_paid + written_off + rows[-1].ending_balance_cents == (
                loan.principal_cents
            )

    def test_terminated_loans_fully_account_for_principal(self, population) -> None:
        for loan, rows in population:
            if rows[-1].loan_status not in TERMINAL_STATUSES:
                continue
            principal_paid = sum(row.principal_paid_cents for row in rows)
            written_off = sum(row.principal_writeoff_cents for row in rows)
            assert principal_paid + written_off == loan.principal_cents

    def test_actual_payment_is_principal_plus_interest(self, population) -> None:
        for _, rows in population:
            for row in rows:
                assert row.actual_payment_cents == (
                    row.principal_paid_cents + row.interest_paid_cents
                )


class TestPrepayment:
    def test_prepayment_rows_close_the_loan(self, population) -> None:
        for _, rows in population:
            for row in rows:
                if row.is_prepayment:
                    assert row is rows[-1]
                    assert row.loan_status == LoanStatus.PAID_OFF
                    assert row.ending_balance_cents == 0


class TestDefaultAndRecovery:
    def test_default_row_writes_off_the_full_open_balance(self, population) -> None:
        for _, rows in population:
            for row in rows:
                if row.principal_writeoff_cents > 0:
                    assert row.delinquency_bucket == DelinquencyBucket.DEFAULT
                    assert row.loan_status == LoanStatus.DEFAULTED
                    assert row.principal_writeoff_cents == row.beginning_balance_cents
                    assert row.ending_balance_cents == 0

    def test_at_most_one_writeoff_per_loan(self, population) -> None:
        for _, rows in population:
            writeoff_rows = [row for row in rows if row.principal_writeoff_cents > 0]
            assert len(writeoff_rows) <= 1

    def test_recovery_arrives_on_schedule_and_completes_the_loan(self, population) -> None:
        calibration = default_calibration()
        for _, rows in population:
            recovery_rows = [row for row in rows if row.recovery_cents > 0]
            if not recovery_rows:
                continue
            recovery_row = recovery_rows[0]
            assert recovery_row is rows[-1]
            assert recovery_row.loan_status == LoanStatus.RECOVERY_COMPLETE
            default_row = next(row for row in rows if row.principal_writeoff_cents > 0)
            assert recovery_row.period - default_row.period == calibration.recovery_lag_months
            assert recovery_row.recovery_cents == round(
                default_row.principal_writeoff_cents
                * calibration.recovery_rate_on_defaulted_balance
            )

    def test_no_payments_after_default(self, population) -> None:
        for _, rows in population:
            defaulted = False
            for row in rows:
                if defaulted:
                    assert row.actual_payment_cents == 0
                if row.loan_status == LoanStatus.DEFAULTED:
                    defaulted = True


class TestReproducibility:
    def test_same_seed_reproduces_identical_rows(self) -> None:
        calibration = default_calibration()

        def simulate(seed: int) -> list[MonthlyPerformance]:
            rng = np.random.default_rng(seed)
            borrower = generate_borrower("B-000000", calibration, rng)
            loan = generate_loan("L-000000", borrower, ORIGINATION_MONTH, calibration, rng)
            return simulate_loan_performance(loan, AS_OF_MONTH, calibration, rng)

        assert simulate(7) == simulate(7)
