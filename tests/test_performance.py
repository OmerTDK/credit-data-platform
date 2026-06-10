"""Property-style tests for the monthly performance simulator.

The invariants here are the product: they hold for every loan in a
fixed-seed population large enough to exercise prepayment, every delinquency
bucket, cure, default, and the recovery flow.
"""

from datetime import date
from itertools import pairwise

import numpy as np
import pytest

from loanbook.amortization import monthly_payment_cents
from loanbook.borrowers import generate_borrower
from loanbook.calibration import SCORE_BANDS, Calibration, default_calibration
from loanbook.loans import PERSONAL_LOAN_PRODUCT_TYPE, Loan, generate_loan
from loanbook.months import MONTHS_PER_YEAR
from loanbook.performance import MonthlyPerformance, simulate_loan_performance
from loanbook.state_machine import (
    MISSED_PAYMENTS_FOR_DEFAULT,
    TERMINAL_STATUSES,
    DelinquencyBucket,
    LoanStatus,
    validate_bucket_transition,
)

POPULATION_SIZE = 2_000
POPULATION_SEED = 42
ORIGINATION_MONTH = date(2020, 1, 1)
AS_OF_MONTH = date(2026, 1, 1)

MAX_ACTIVE_MONTHS_PAST_MATURITY = MISSED_PAYMENTS_FOR_DEFAULT - 1


def months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * MONTHS_PER_YEAR + later.month - earlier.month


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


CUMULATIVE_DEFAULT_RATE_SANE_BANDS = {
    "subprime": (0.25, 0.60),
    "near_prime": (0.15, 0.45),
    "prime": (0.04, 0.20),
    "prime_plus": (0.01, 0.12),
    "super_prime": (0.0, 0.06),
}
SCORE_BANDS_BEST_TO_WORST = ("super_prime", "prime_plus", "prime", "near_prime", "subprime")


class TestAggregateOutcomes:
    """Aggregate realizations that pin the hazard wiring, not just row validity.

    A sign-flipped or disconnected hazard produces rows that satisfy every
    per-row invariant; what it cannot produce is the calibrated population
    shape — default rates within a sane band per score band, monotone across
    bands, with prepayments and cures realized.
    """

    def cumulative_default_rate_by_band(self, population) -> dict[str, float]:
        terminal_horizon_months = (
            MAX_ACTIVE_MONTHS_PAST_MATURITY + default_calibration().recovery_lag_months
        )
        loan_count_by_band: dict[str, int] = dict.fromkeys(SCORE_BANDS_BEST_TO_WORST, 0)
        default_count_by_band: dict[str, int] = dict.fromkeys(SCORE_BANDS_BEST_TO_WORST, 0)
        for loan, rows in population:
            fully_observed = (
                months_between(loan.origination_month, AS_OF_MONTH)
                >= loan.term_months + terminal_horizon_months
            )
            if not fully_observed:
                continue
            loan_count_by_band[loan.score_band] += 1
            if any(row.principal_writeoff_cents > 0 for row in rows):
                default_count_by_band[loan.score_band] += 1
        return {
            band: default_count_by_band[band] / loan_count_by_band[band]
            for band in SCORE_BANDS_BEST_TO_WORST
        }

    def test_cumulative_default_rate_is_sane_per_score_band(self, population) -> None:
        rate_by_band = self.cumulative_default_rate_by_band(population)
        for band, (lower_bound, upper_bound) in CUMULATIVE_DEFAULT_RATE_SANE_BANDS.items():
            assert lower_bound <= rate_by_band[band] <= upper_bound, (
                f"{band} cumulative default rate {rate_by_band[band]:.4f} outside "
                f"sane band [{lower_bound}, {upper_bound}]"
            )

    def test_cumulative_default_rate_increases_as_score_band_worsens(self, population) -> None:
        rate_by_band = self.cumulative_default_rate_by_band(population)
        rates_best_to_worst = [rate_by_band[band] for band in SCORE_BANDS_BEST_TO_WORST]
        for better_rate, worse_rate in pairwise(rates_best_to_worst):
            assert better_rate < worse_rate, f"default rates not ordered: {rate_by_band}"

    def test_prepayment_occurs_in_every_score_band(self, population) -> None:
        bands_with_prepayment = {
            loan.score_band for loan, rows in population if any(row.is_prepayment for row in rows)
        }
        assert bands_with_prepayment == set(SCORE_BANDS_BEST_TO_WORST)

    def test_cures_occur(self, population) -> None:
        cure_count = sum(
            1
            for _, rows in population
            for earlier, later in pairwise(rows)
            if earlier.delinquency_bucket != DelinquencyBucket.CURRENT
            and later.delinquency_bucket == DelinquencyBucket.CURRENT
        )
        assert cure_count > 0


def three_month_loan() -> Loan:
    principal_cents = 90_000
    interest_rate = 0.12
    term_months = 3
    return Loan(
        loan_id="L-MATURED",
        borrower_id="B-MATURED",
        product_type=PERSONAL_LOAN_PRODUCT_TYPE,
        origination_month=date(2022, 1, 1),
        principal_cents=principal_cents,
        term_months=term_months,
        interest_rate=interest_rate,
        monthly_payment_cents=monthly_payment_cents(principal_cents, interest_rate, term_months),
        score_band="prime",
    )


def forcing_calibration(roll_probabilities: dict[str, dict[str, float]]) -> Calibration:
    """Calibration with 0/1 hazards so the simulated path is exact, not sampled."""
    band_names = [band.name for band in SCORE_BANDS]
    return Calibration(
        monthly_delinquency_entry_hazard_by_band=dict.fromkeys(band_names, 1.0),
        monthly_prepayment_rate_by_band=dict.fromkeys(band_names, 0.0),
        delinquent_roll_probabilities=roll_probabilities,
    )


class TestPostMaturityResolution:
    """Matured loans with arrears must resolve: cure in full or roll deeper monthly.

    The rule (ADR-0002): past maturity nothing new comes due, but the unpaid
    arrears age 30 more days each month, so the bucket deepens every month the
    borrower fails to cure — 90+ that fails to cure defaults. A loan therefore
    never stays ACTIVE more than MAX_ACTIVE_MONTHS_PAST_MATURITY months past
    maturity, and reaches a terminal state within that bound plus the recovery
    lag.
    """

    def simulate_forced(
        self, roll_probabilities: dict[str, dict[str, float]]
    ) -> tuple[Loan, list[MonthlyPerformance]]:
        loan = three_month_loan()
        calibration = forcing_calibration(roll_probabilities)
        rows = simulate_loan_performance(
            loan, date(2023, 6, 1), calibration, np.random.default_rng(POPULATION_SEED)
        )
        return loan, rows

    def test_matured_delinquent_loan_rolls_deeper_monthly_to_default(self) -> None:
        stay_until_maturity = {"cure": 0.0, "stay": 1.0, "roll_deeper": 0.0}
        loan, rows = self.simulate_forced(
            {
                "dpd_30": stay_until_maturity,
                "dpd_60": stay_until_maturity,
                "dpd_90_plus": stay_until_maturity,
            }
        )
        assert [row.delinquency_bucket for row in rows[:6]] == [
            DelinquencyBucket.DPD_30,
            DelinquencyBucket.DPD_30,
            DelinquencyBucket.DPD_30,
            DelinquencyBucket.DPD_60,
            DelinquencyBucket.DPD_90_PLUS,
            DelinquencyBucket.DEFAULT,
        ]
        default_row = rows[5]
        assert default_row.loan_status == LoanStatus.DEFAULTED
        assert default_row.period == loan.term_months + MAX_ACTIVE_MONTHS_PAST_MATURITY
        assert rows[-1].loan_status == LoanStatus.RECOVERY_COMPLETE
        assert rows[-1].period == default_row.period + default_calibration().recovery_lag_months

    def test_post_maturity_aging_months_move_no_money(self) -> None:
        stay_until_maturity = {"cure": 0.0, "stay": 1.0, "roll_deeper": 0.0}
        loan, rows = self.simulate_forced(
            {
                "dpd_30": stay_until_maturity,
                "dpd_60": stay_until_maturity,
                "dpd_90_plus": stay_until_maturity,
            }
        )
        aging_rows = [
            row
            for row in rows
            if row.period > loan.term_months and row.loan_status == LoanStatus.ACTIVE
        ]
        assert aging_rows
        for row in aging_rows:
            assert row.actual_payment_cents == 0
            assert row.scheduled_payment_cents == 0
            assert row.ending_balance_cents == row.beginning_balance_cents

    def test_matured_delinquent_loan_cures_in_full_and_pays_off(self) -> None:
        loan, rows = self.simulate_forced(
            {
                "dpd_30": {"cure": 0.0, "stay": 1.0, "roll_deeper": 0.0},
                "dpd_60": {"cure": 1.0, "stay": 0.0, "roll_deeper": 0.0},
                "dpd_90_plus": {"cure": 1.0, "stay": 0.0, "roll_deeper": 0.0},
            }
        )
        final_row = rows[-1]
        assert final_row.loan_status == LoanStatus.PAID_OFF
        assert final_row.period == loan.term_months + 2
        assert final_row.delinquency_bucket == DelinquencyBucket.CURRENT
        assert final_row.ending_balance_cents == 0

    def test_loan_entering_maturity_at_90_plus_defaults_within_one_month(self) -> None:
        always_roll_deeper = {"cure": 0.0, "stay": 0.0, "roll_deeper": 1.0}
        loan, rows = self.simulate_forced(
            {
                "dpd_30": always_roll_deeper,
                "dpd_60": always_roll_deeper,
                "dpd_90_plus": always_roll_deeper,
            }
        )
        maturity_row = rows[loan.term_months - 1]
        assert maturity_row.delinquency_bucket == DelinquencyBucket.DPD_90_PLUS
        assert maturity_row.loan_status == LoanStatus.ACTIVE
        default_row = rows[loan.term_months]
        assert default_row.loan_status == LoanStatus.DEFAULTED
        assert default_row.period == loan.term_months + 1
        assert default_row.principal_writeoff_cents == loan.principal_cents
        assert rows[-1].loan_status == LoanStatus.RECOVERY_COMPLETE
        assert rows[-1].period == loan.term_months + 1 + default_calibration().recovery_lag_months

    def test_no_loan_remains_active_beyond_the_bound_past_maturity(self, population) -> None:
        for loan, rows in population:
            for row in rows:
                if row.loan_status == LoanStatus.ACTIVE:
                    assert row.period <= loan.term_months + MAX_ACTIVE_MONTHS_PAST_MATURITY

    def test_every_fully_observed_loan_reaches_a_terminal_state(self, population) -> None:
        terminal_horizon_months = (
            MAX_ACTIVE_MONTHS_PAST_MATURITY + default_calibration().recovery_lag_months
        )
        fully_observed = [
            (loan, rows)
            for loan, rows in population
            if months_between(loan.origination_month, AS_OF_MONTH)
            >= loan.term_months + terminal_horizon_months
        ]
        assert fully_observed
        for _, rows in fully_observed:
            assert rows[-1].loan_status in TERMINAL_STATUSES

    def test_population_exercises_post_maturity_default(self, population) -> None:
        assert any(
            row.principal_writeoff_cents > 0 and row.period > loan.term_months
            for loan, rows in population
            for row in rows
        )


class TestReproducibility:
    def test_same_seed_reproduces_identical_rows(self) -> None:
        calibration = default_calibration()

        def simulate(seed: int) -> list[MonthlyPerformance]:
            rng = np.random.default_rng(seed)
            borrower = generate_borrower("B-000000", calibration, rng)
            loan = generate_loan("L-000000", borrower, ORIGINATION_MONTH, calibration, rng)
            return simulate_loan_performance(loan, AS_OF_MONTH, calibration, rng)

        assert simulate(7) == simulate(7)
