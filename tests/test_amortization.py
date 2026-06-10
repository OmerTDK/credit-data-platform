"""Tests for the cent-exact annuity amortization schedule."""

import pytest

from loanbook.amortization import build_amortization_schedule, monthly_payment_cents


class TestMonthlyPayment:
    def test_known_annuity_value(self) -> None:
        # 1,200.00 at 12% APR over 12 months: standard annuity payment is 106.62
        assert monthly_payment_cents(120_000, 0.12, 12) == 10_662

    def test_payment_covers_first_month_interest(self) -> None:
        payment = monthly_payment_cents(1_000_000, 0.24, 36)
        first_month_interest = round(1_000_000 * 0.24 / 12)
        assert payment > first_month_interest

    @pytest.mark.parametrize(
        ("principal_cents", "annual_rate", "term_months"),
        [
            (0, 0.12, 12),
            (-100, 0.12, 12),
            (120_000, 0.0, 12),
            (120_000, -0.01, 12),
            (120_000, 0.12, 0),
            (120_000, 0.12, -3),
        ],
    )
    def test_rejects_non_positive_inputs(
        self, principal_cents: int, annual_rate: float, term_months: int
    ) -> None:
        with pytest.raises(ValueError):
            monthly_payment_cents(principal_cents, annual_rate, term_months)


class TestAmortizationSchedule:
    def test_schedule_has_one_entry_per_month(self) -> None:
        schedule = build_amortization_schedule(120_000, 0.12, 12)
        assert len(schedule) == 12

    def test_principal_portions_sum_exactly_to_principal(self) -> None:
        schedule = build_amortization_schedule(987_654, 0.1799, 36)
        assert sum(entry.principal_cents for entry in schedule) == 987_654

    def test_balances_decrease_to_exactly_zero(self) -> None:
        schedule = build_amortization_schedule(2_500_000, 0.0749, 60)
        balances = [entry.ending_balance_cents for entry in schedule]
        assert all(balances[i] > balances[i + 1] for i in range(len(balances) - 1))
        assert balances[-1] == 0

    def test_no_balance_is_negative(self) -> None:
        schedule = build_amortization_schedule(100_001, 0.2899, 36)
        assert all(entry.ending_balance_cents >= 0 for entry in schedule)

    def test_interest_is_monthly_rate_on_open_balance(self) -> None:
        schedule = build_amortization_schedule(120_000, 0.12, 12)
        assert schedule[0].interest_cents == round(120_000 * 0.01)

    def test_all_payments_equal_except_final_adjustment(self) -> None:
        schedule = build_amortization_schedule(987_654, 0.1799, 36)
        payments = [entry.payment_cents for entry in schedule]
        assert len(set(payments[:-1])) == 1

    def test_each_payment_is_interest_plus_principal(self) -> None:
        schedule = build_amortization_schedule(987_654, 0.1799, 36)
        for entry in schedule:
            assert entry.payment_cents == entry.interest_cents + entry.principal_cents

    def test_period_numbers_start_at_one_and_are_contiguous(self) -> None:
        schedule = build_amortization_schedule(120_000, 0.12, 12)
        assert [entry.period for entry in schedule] == list(range(1, 13))
