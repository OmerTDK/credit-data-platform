"""Tests for whole-book generation across origination cohorts."""

from datetime import date

import pytest

from loanbook.generate import GeneratorConfig, LoanBook, generate_loan_book


@pytest.fixture(scope="module")
def small_book() -> LoanBook:
    config = GeneratorConfig(
        seed=42,
        cohort_count=6,
        loans_per_cohort=50,
        start_month=date(2022, 1, 1),
        as_of_month=date(2024, 12, 1),
    )
    return generate_loan_book(config)


class TestGenerateLoanBook:
    def test_book_has_one_loan_per_borrower(self, small_book: LoanBook) -> None:
        assert len(small_book.loans) == 6 * 50
        assert len(small_book.borrowers) == len(small_book.loans)

    def test_loan_and_borrower_ids_are_unique(self, small_book: LoanBook) -> None:
        loan_ids = [loan.loan_id for loan in small_book.loans]
        borrower_ids = [borrower.borrower_id for borrower in small_book.borrowers]
        assert len(set(loan_ids)) == len(loan_ids)
        assert len(set(borrower_ids)) == len(borrower_ids)

    def test_every_loan_references_an_existing_borrower(self, small_book: LoanBook) -> None:
        borrower_ids = {borrower.borrower_id for borrower in small_book.borrowers}
        assert all(loan.borrower_id in borrower_ids for loan in small_book.loans)

    def test_cohorts_cover_the_configured_window(self, small_book: LoanBook) -> None:
        origination_months = {loan.origination_month for loan in small_book.loans}
        assert origination_months == {
            date(2022, 1, 1),
            date(2022, 2, 1),
            date(2022, 3, 1),
            date(2022, 4, 1),
            date(2022, 5, 1),
            date(2022, 6, 1),
        }

    def test_each_cohort_has_the_configured_size(self, small_book: LoanBook) -> None:
        cohort_sizes: dict[date, int] = {}
        for loan in small_book.loans:
            cohort_sizes[loan.origination_month] = cohort_sizes.get(loan.origination_month, 0) + 1
        assert set(cohort_sizes.values()) == {50}

    def test_performance_covers_every_loan(self, small_book: LoanBook) -> None:
        loans_with_rows = {row.loan_id for row in small_book.monthly_performance}
        assert loans_with_rows == {loan.loan_id for loan in small_book.loans}

    def test_default_as_of_is_twelve_months_after_last_cohort(self) -> None:
        config = GeneratorConfig(seed=1, cohort_count=6, loans_per_cohort=1)
        assert config.start_month == date(2022, 1, 1)
        assert config.as_of_month == date(2023, 6, 1)

    def test_rejects_non_positive_dimensions(self) -> None:
        with pytest.raises(ValueError, match="cohort_count"):
            GeneratorConfig(seed=1, cohort_count=0, loans_per_cohort=10)
        with pytest.raises(ValueError, match="loans_per_cohort"):
            GeneratorConfig(seed=1, cohort_count=10, loans_per_cohort=-1)

    def test_rejects_as_of_before_first_cohort(self) -> None:
        with pytest.raises(ValueError, match="as_of_month"):
            GeneratorConfig(
                seed=1,
                cohort_count=6,
                loans_per_cohort=10,
                start_month=date(2022, 1, 1),
                as_of_month=date(2021, 12, 1),
            )

    def test_rejects_as_of_inside_the_cohort_span(self) -> None:
        with pytest.raises(ValueError, match="cohort"):
            GeneratorConfig(
                seed=1,
                cohort_count=6,
                loans_per_cohort=10,
                start_month=date(2022, 1, 1),
                as_of_month=date(2022, 3, 1),
            )

    def test_accepts_as_of_equal_to_the_last_cohort_month(self) -> None:
        config = GeneratorConfig(
            seed=1,
            cohort_count=6,
            loans_per_cohort=10,
            start_month=date(2022, 1, 1),
            as_of_month=date(2022, 6, 1),
        )
        assert config.as_of_month == date(2022, 6, 1)

    def test_same_config_generates_identical_books(self, small_book: LoanBook) -> None:
        config = GeneratorConfig(
            seed=42,
            cohort_count=6,
            loans_per_cohort=50,
            start_month=date(2022, 1, 1),
            as_of_month=date(2024, 12, 1),
        )
        regenerated = generate_loan_book(config)
        assert regenerated.loans == small_book.loans
        assert regenerated.borrowers == small_book.borrowers
        assert regenerated.monthly_performance == small_book.monthly_performance
