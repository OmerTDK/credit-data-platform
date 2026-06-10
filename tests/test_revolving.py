"""Property-style tests for the revolving card simulator.

Cards have no maturity: a never-delinquent account emits a row every month
through the as-of cutoff. The terminal path is charge-off at 6 missed minimum
payments (180 days past due, FFIEC open-end rule) followed by the recovery
flow. Forced 0/1 calibrations pin the exact monthly mechanics; the fixed-seed
population pins the invariants and the aggregate shape.
"""

from dataclasses import replace
from datetime import date
from itertools import pairwise
from typing import ClassVar

import numpy as np
import pytest

from loanbook.borrowers import generate_borrower
from loanbook.calibration import Calibration, default_calibration
from loanbook.loans import Loan, generate_loan
from loanbook.months import MONTHS_PER_YEAR
from loanbook.performance import MonthlyPerformance, simulate_loan_performance
from loanbook.products import ProductType
from loanbook.state_machine import (
    MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING,
    DelinquencyBucket,
    LoanStatus,
    validate_bucket_transition,
)

POPULATION_SIZE = 1_200
POPULATION_SEED = 42
ORIGINATION_MONTH = date(2019, 1, 1)
AS_OF_MONTH = date(2026, 1, 1)

CARD_CALIBRATION = default_calibration().credit_card
UTILIZATION_DECIMAL_PLACES = 6
# A maxed-out account can sit delinquent for at most 5 months before the
# 180-day charge-off, capitalizing up to ~2.4% monthly subprime interest each
# month — so the carried balance can exceed the limit by ~12%, never more.
INTEREST_OVER_LIMIT_TOLERANCE = 1.15

SCORE_BANDS_BEST_TO_WORST = ("super_prime", "prime_plus", "prime", "near_prime", "subprime")
WORST_BANDS_STRICTLY_ORDERED = ("prime", "near_prime", "subprime")

CHARGE_OFF_RATE_SANE_BANDS = {
    "subprime": (0.15, 0.55),
    "near_prime": (0.05, 0.35),
    "prime": (0.01, 0.20),
    "prime_plus": (0.0, 0.12),
    "super_prime": (0.0, 0.06),
}


def months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * MONTHS_PER_YEAR + later.month - earlier.month


def generate_card(calibration: Calibration, rng: np.random.Generator, index: int = 0) -> Loan:
    borrower = generate_borrower(f"B-{index:06d}", calibration, rng)
    return generate_loan(
        f"L-{index:06d}", borrower, ProductType.CREDIT_CARD, ORIGINATION_MONTH, calibration, rng
    )


@pytest.fixture(scope="module")
def population() -> list[tuple[Loan, list[MonthlyPerformance]]]:
    calibration = default_calibration()
    rng = np.random.default_rng(POPULATION_SEED)
    simulated = []
    for index in range(POPULATION_SIZE):
        card = generate_card(calibration, rng, index)
        rows = simulate_loan_performance(card, AS_OF_MONTH, calibration, rng)
        simulated.append((card, rows))
    return simulated


def forcing_card_calibration(
    miss_hazard: float,
    pay_in_full_probability: float,
    roll_probabilities: dict[str, dict[str, float]] | None = None,
) -> Calibration:
    """Calibration with 0/1 card behavior so the simulated path is exact."""
    default = default_calibration()
    bands = dict.fromkeys(SCORE_BANDS_BEST_TO_WORST, 0.0)
    forced_card = replace(
        default.credit_card,
        monthly_delinquency_entry_hazard_by_band={**bands, **dict.fromkeys(bands, miss_hazard)},
        pay_in_full_probability_by_band=dict.fromkeys(bands, pay_in_full_probability),
        delinquent_roll_probabilities=(
            roll_probabilities or default.credit_card.delinquent_roll_probabilities
        ),
    )
    return replace(default, credit_card=forced_card)


def simulate_forced(calibration: Calibration) -> tuple[Loan, list[MonthlyPerformance]]:
    rng = np.random.default_rng(POPULATION_SEED)
    card = generate_card(calibration, rng)
    return card, simulate_loan_performance(card, AS_OF_MONTH, calibration, rng)


def expected_minimum_due(row: MonthlyPerformance, card_calibration=CARD_CALIBRATION) -> int:
    statement = row.beginning_balance_cents + row.draw_cents + row.interest_charged_cents
    formula = row.interest_charged_cents + round(
        card_calibration.minimum_payment_principal_rate * statement
    )
    return min(max(formula, card_calibration.minimum_payment_floor_cents), statement)


class TestForcedChargeOffPath:
    ALWAYS_ROLL: ClassVar[dict] = {
        "dpd_30": {"cure": 0.0, "stay": 0.0, "roll_deeper": 1.0},
        "dpd_60": {"cure": 0.0, "stay": 0.0, "roll_deeper": 1.0},
        "dpd_90_plus": {"cure": 0.0, "stay": 0.0, "roll_deeper": 1.0},
    }

    @pytest.fixture(scope="class")
    def forced(self) -> tuple[Loan, list[MonthlyPerformance]]:
        return simulate_forced(
            forcing_card_calibration(
                miss_hazard=1.0, pay_in_full_probability=0.0, roll_probabilities=self.ALWAYS_ROLL
            )
        )

    def test_buckets_age_monthly_and_charge_off_at_180_days(self, forced) -> None:
        _, rows = forced
        assert [row.delinquency_bucket for row in rows[:6]] == [
            DelinquencyBucket.DPD_30,
            DelinquencyBucket.DPD_60,
            DelinquencyBucket.DPD_90_PLUS,
            DelinquencyBucket.DPD_90_PLUS,
            DelinquencyBucket.DPD_90_PLUS,
            DelinquencyBucket.DEFAULT,
        ]
        assert rows[5].period == MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING

    def test_charge_off_writes_off_the_full_balance_and_stops_activity(self, forced) -> None:
        _, rows = forced
        charge_off_row = rows[5]
        assert charge_off_row.loan_status == LoanStatus.DEFAULTED
        assert charge_off_row.principal_writeoff_cents == charge_off_row.beginning_balance_cents
        assert charge_off_row.principal_writeoff_cents > 0
        assert charge_off_row.ending_balance_cents == 0
        assert charge_off_row.draw_cents == 0
        assert charge_off_row.interest_charged_cents == 0
        assert charge_off_row.actual_payment_cents == 0

    def test_recovery_arrives_on_schedule_and_completes_the_account(self, forced) -> None:
        _, rows = forced
        charge_off_row = rows[5]
        recovery_row = rows[-1]
        assert recovery_row.loan_status == LoanStatus.RECOVERY_COMPLETE
        assert recovery_row.period == (charge_off_row.period + CARD_CALIBRATION.recovery_lag_months)
        assert recovery_row.recovery_cents == round(
            charge_off_row.principal_writeoff_cents
            * CARD_CALIBRATION.recovery_rate_on_charged_off_balance
        )

    def test_no_draws_while_delinquent(self, forced) -> None:
        _, rows = forced
        assert rows[0].draw_cents > 0
        assert all(row.draw_cents == 0 for row in rows[1:])

    def test_payment_below_the_interest_charge_goes_entirely_to_interest(self, forced) -> None:
        _, rows = forced
        short_paying_rows = [
            row for row in rows if row.actual_payment_cents < row.interest_charged_cents
        ]
        assert len(short_paying_rows) == 4
        for row in short_paying_rows:
            assert row.interest_paid_cents == row.actual_payment_cents
            assert row.principal_paid_cents == 0


class TestForcedTransactorPath:
    @pytest.fixture(scope="class")
    def forced(self) -> tuple[Loan, list[MonthlyPerformance]]:
        return simulate_forced(forcing_card_calibration(0.0, 1.0))

    def test_transactor_pays_in_full_every_month_with_no_interest(self, forced) -> None:
        _, rows = forced
        assert rows
        for row in rows:
            assert row.interest_charged_cents == 0
            assert row.ending_balance_cents == 0
            assert row.actual_payment_cents == row.beginning_balance_cents + row.draw_cents
            assert row.delinquency_bucket == DelinquencyBucket.CURRENT
            assert row.utilization_rate == 0.0

    def test_open_account_emits_a_row_every_month_through_as_of(self, forced) -> None:
        card, rows = forced
        assert len(rows) == months_between(card.origination_month, AS_OF_MONTH)
        assert all(row.loan_status == LoanStatus.ACTIVE for row in rows)


class TestForcedRevolverPath:
    @pytest.fixture(scope="class")
    def forced(self) -> tuple[Loan, list[MonthlyPerformance]]:
        return simulate_forced(forcing_card_calibration(0.0, 0.0))

    def test_revolver_pays_exactly_the_minimum_due(self, forced) -> None:
        _, rows = forced
        for row in rows:
            assert row.scheduled_payment_cents == expected_minimum_due(row)
            assert row.actual_payment_cents == row.scheduled_payment_cents

    def test_revolver_carries_a_balance_and_accrues_interest(self, forced) -> None:
        _, rows = forced
        assert all(row.ending_balance_cents > 0 for row in rows)
        assert any(row.interest_charged_cents > 0 for row in rows)

    def test_revolver_utilization_settles_near_the_band_target(self, forced) -> None:
        card, rows = forced
        target = CARD_CALIBRATION.target_utilization_by_band[card.score_band]
        settled_rows = rows[12:]
        assert settled_rows
        mean_utilization = sum(row.utilization_rate for row in settled_rows) / len(settled_rows)
        assert abs(mean_utilization - target) < 0.2


class TestForcedCurePath:
    ALWAYS_CURE: ClassVar[dict] = {
        "dpd_30": {"cure": 1.0, "stay": 0.0, "roll_deeper": 0.0},
        "dpd_60": {"cure": 1.0, "stay": 0.0, "roll_deeper": 0.0},
        "dpd_90_plus": {"cure": 1.0, "stay": 0.0, "roll_deeper": 0.0},
    }

    @pytest.fixture(scope="class")
    def forced(self) -> tuple[Loan, list[MonthlyPerformance]]:
        return simulate_forced(
            forcing_card_calibration(
                miss_hazard=1.0, pay_in_full_probability=0.0, roll_probabilities=self.ALWAYS_CURE
            )
        )

    def test_account_alternates_between_missing_and_curing(self, forced) -> None:
        _, rows = forced
        for index, row in enumerate(rows):
            expected_bucket = (
                DelinquencyBucket.DPD_30 if index % 2 == 0 else DelinquencyBucket.CURRENT
            )
            assert row.delinquency_bucket == expected_bucket

    def test_cure_pays_the_arrears_plus_the_current_minimum(self, forced) -> None:
        _, rows = forced
        for miss_row, cure_row in pairwise(rows):
            if cure_row.delinquency_bucket != DelinquencyBucket.CURRENT:
                continue
            arrears = miss_row.scheduled_payment_cents
            statement = (
                cure_row.beginning_balance_cents
                + cure_row.draw_cents
                + cure_row.interest_charged_cents
            )
            assert cure_row.actual_payment_cents == min(
                arrears + expected_minimum_due(cure_row), statement
            )


class TestRowShape:
    def test_rows_carry_the_card_product_type(self, population) -> None:
        for _, rows in population:
            assert all(row.product_type == ProductType.CREDIT_CARD.value for row in rows)

    def test_periods_are_contiguous_from_one(self, population) -> None:
        for _, rows in population:
            assert [row.period for row in rows] == list(range(1, len(rows) + 1))

    def test_accounts_not_charged_off_emit_rows_through_as_of(self, population) -> None:
        full_span = months_between(ORIGINATION_MONTH, AS_OF_MONTH)
        for _, rows in population:
            if rows[-1].loan_status == LoanStatus.ACTIVE:
                assert len(rows) == full_span

    def test_cards_never_prepay_and_never_pay_off(self, population) -> None:
        for _, rows in population:
            for row in rows:
                assert not row.is_prepayment
                assert row.loan_status != LoanStatus.PAID_OFF


class TestBalanceIntegrity:
    def test_balances_and_draws_are_never_negative(self, population) -> None:
        for _, rows in population:
            for row in rows:
                assert row.beginning_balance_cents >= 0
                assert row.ending_balance_cents >= 0
                assert row.draw_cents >= 0

    def test_each_row_satisfies_the_universal_balance_identity(self, population) -> None:
        for _, rows in population:
            for row in rows:
                assert row.ending_balance_cents == (
                    row.beginning_balance_cents
                    + row.draw_cents
                    + row.interest_charged_cents
                    - row.interest_paid_cents
                    - row.principal_paid_cents
                    - row.principal_writeoff_cents
                )

    def test_actual_payment_is_principal_plus_interest(self, population) -> None:
        for _, rows in population:
            for row in rows:
                assert row.actual_payment_cents == (
                    row.principal_paid_cents + row.interest_paid_cents
                )

    def test_interest_paid_never_exceeds_the_actual_payment(self, population) -> None:
        for _, rows in population:
            for row in rows:
                assert row.interest_paid_cents <= row.actual_payment_cents

    def test_principal_paid_is_never_negative(self, population) -> None:
        for _, rows in population:
            for row in rows:
                assert row.principal_paid_cents >= 0

    def test_draws_never_push_the_balance_above_the_limit(self, population) -> None:
        for card, rows in population:
            for row in rows:
                if row.draw_cents > 0:
                    assert row.beginning_balance_cents + row.draw_cents <= card.credit_limit_cents

    def test_balance_exceeds_the_limit_only_through_accrued_interest(self, population) -> None:
        for card, rows in population:
            for row in rows:
                assert row.ending_balance_cents <= (
                    card.credit_limit_cents * INTEREST_OVER_LIMIT_TOLERANCE
                )

    def test_utilization_is_the_ending_balance_share_of_the_limit(self, population) -> None:
        for card, rows in population:
            for row in rows:
                assert row.utilization_rate == round(
                    row.ending_balance_cents / card.credit_limit_cents,
                    UTILIZATION_DECIMAL_PLACES,
                )


class TestDelinquencyAndChargeOff:
    def test_every_consecutive_transition_is_legal(self, population) -> None:
        for _, rows in population:
            for earlier, later in pairwise(rows):
                validate_bucket_transition(earlier.delinquency_bucket, later.delinquency_bucket)

    def test_charge_off_writes_off_the_full_balance(self, population) -> None:
        for _, rows in population:
            for row in rows:
                if row.principal_writeoff_cents > 0:
                    assert row.delinquency_bucket == DelinquencyBucket.DEFAULT
                    assert row.loan_status == LoanStatus.DEFAULTED
                    assert row.principal_writeoff_cents == row.beginning_balance_cents
                    assert row.ending_balance_cents == 0

    def test_at_most_one_charge_off_per_account(self, population) -> None:
        for _, rows in population:
            writeoff_rows = [row for row in rows if row.principal_writeoff_cents > 0]
            assert len(writeoff_rows) <= 1

    def test_no_payments_or_draws_after_charge_off(self, population) -> None:
        for _, rows in population:
            charged_off = False
            for row in rows:
                if charged_off:
                    assert row.actual_payment_cents == 0
                    assert row.draw_cents == 0
                if row.loan_status == LoanStatus.DEFAULTED:
                    charged_off = True

    def test_recovery_completes_charged_off_accounts(self, population) -> None:
        for _, rows in population:
            recovery_rows = [row for row in rows if row.recovery_cents > 0]
            if not recovery_rows:
                continue
            recovery_row = recovery_rows[0]
            assert recovery_row is rows[-1]
            assert recovery_row.loan_status == LoanStatus.RECOVERY_COMPLETE
            charge_off_row = next(row for row in rows if row.principal_writeoff_cents > 0)
            assert recovery_row.period - charge_off_row.period == (
                CARD_CALIBRATION.recovery_lag_months
            )

    def test_delinquent_months_have_no_draws(self, population) -> None:
        for _, rows in population:
            for earlier, later in pairwise(rows):
                if earlier.delinquency_bucket != DelinquencyBucket.CURRENT:
                    assert later.draw_cents == 0


class TestAggregateOutcomes:
    """Aggregate realizations that pin the revolving hazard wiring."""

    def charge_off_rate_by_band(self, population) -> dict[str, float]:
        account_count = dict.fromkeys(SCORE_BANDS_BEST_TO_WORST, 0)
        charge_off_count = dict.fromkeys(SCORE_BANDS_BEST_TO_WORST, 0)
        for card, rows in population:
            account_count[card.score_band] += 1
            if any(row.principal_writeoff_cents > 0 for row in rows):
                charge_off_count[card.score_band] += 1
        return {
            band: charge_off_count[band] / account_count[band] for band in SCORE_BANDS_BEST_TO_WORST
        }

    def test_charge_off_rate_is_sane_per_score_band(self, population) -> None:
        rate_by_band = self.charge_off_rate_by_band(population)
        for band, (lower_bound, upper_bound) in CHARGE_OFF_RATE_SANE_BANDS.items():
            assert lower_bound <= rate_by_band[band] <= upper_bound, (
                f"credit_card {band} charge-off rate {rate_by_band[band]:.4f} outside "
                f"sane band [{lower_bound}, {upper_bound}]"
            )

    def test_charge_off_rate_increases_as_score_band_worsens(self, population) -> None:
        rate_by_band = self.charge_off_rate_by_band(population)
        worst_rates = [rate_by_band[band] for band in WORST_BANDS_STRICTLY_ORDERED]
        for better_rate, worse_rate in pairwise(worst_rates):
            assert better_rate < worse_rate, f"charge-off rates not ordered: {rate_by_band}"
        assert rate_by_band["super_prime"] < rate_by_band["prime"]
        assert rate_by_band["prime_plus"] < rate_by_band["prime"]

    def test_population_exercises_every_bucket_and_cures(self, population) -> None:
        all_rows = [row for _, rows in population for row in rows]
        assert {row.delinquency_bucket for row in all_rows} == set(DelinquencyBucket)
        cure_count = sum(
            1
            for _, rows in population
            for earlier, later in pairwise(rows)
            if earlier.delinquency_bucket != DelinquencyBucket.CURRENT
            and later.delinquency_bucket == DelinquencyBucket.CURRENT
        )
        assert cure_count > 0

    def test_population_exercises_transactor_and_revolver_months(self, population) -> None:
        all_rows = [row for _, rows in population for row in rows]
        assert any(
            row.ending_balance_cents == 0 and row.actual_payment_cents > 0 for row in all_rows
        )
        assert any(row.interest_charged_cents > 0 for row in all_rows)

    def test_utilization_increases_as_score_band_worsens(self, population) -> None:
        final_utilization_by_band: dict[str, list[float]] = {
            band: [] for band in SCORE_BANDS_BEST_TO_WORST
        }
        for card, rows in population:
            if rows[-1].loan_status == LoanStatus.ACTIVE:
                final_utilization_by_band[card.score_band].append(rows[-1].utilization_rate)
        mean_by_band = {
            band: sum(values) / len(values) for band, values in final_utilization_by_band.items()
        }
        for better, worse in pairwise([mean_by_band[band] for band in SCORE_BANDS_BEST_TO_WORST]):
            assert worse > better, f"utilization not ordered: {mean_by_band}"


class TestReproducibility:
    def test_same_seed_reproduces_identical_rows(self) -> None:
        calibration = default_calibration()

        def simulate(seed: int) -> list[MonthlyPerformance]:
            rng = np.random.default_rng(seed)
            card = generate_card(calibration, rng)
            return simulate_loan_performance(card, AS_OF_MONTH, calibration, rng)

        assert simulate(7) == simulate(7)
