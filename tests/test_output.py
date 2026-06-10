"""Tests for parquet landing-zone output: layout, types, and DuckDB readability."""

from datetime import date
from pathlib import Path

import duckdb
import pytest

from loanbook.generate import GeneratorConfig, generate_loan_book
from loanbook.output import write_loan_book

CONFIG = GeneratorConfig(
    seed=42,
    cohort_count=3,
    loans_per_cohort=40,
    start_month=date(2022, 1, 1),
    as_of_month=date(2023, 6, 1),
)


@pytest.fixture(scope="module")
def landing_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    landing = tmp_path_factory.mktemp("landing")
    book = generate_loan_book(CONFIG)
    write_loan_book(book, landing)
    return landing


class TestLandingLayout:
    def test_writes_one_file_per_entity_table(self, landing_dir: Path) -> None:
        assert (landing_dir / "loans" / "loans.parquet").is_file()
        assert (landing_dir / "borrowers" / "borrowers.parquet").is_file()

    def test_partitions_performance_by_report_month(self, landing_dir: Path) -> None:
        partition_dirs = sorted(
            path.name for path in (landing_dir / "monthly_performance").iterdir()
        )
        assert partition_dirs[0] == "report_year_month=2022-02"
        assert partition_dirs[-1] == "report_year_month=2023-06"
        for partition_dir in partition_dirs:
            assert (landing_dir / "monthly_performance" / partition_dir / "rows.parquet").is_file()

    def test_report_month_inside_files_is_a_date_not_shadowed_by_the_partition_key(
        self, landing_dir: Path
    ) -> None:
        column_type = duckdb.sql(
            f"SELECT typeof(report_month) FROM read_parquet("
            f"'{landing_dir}/monthly_performance/*/*.parquet', hive_partitioning = true) LIMIT 1"
        ).fetchone()[0]
        assert column_type == "DATE"


class TestDuckDbReadability:
    def test_loans_row_count_matches_book(self, landing_dir: Path) -> None:
        count = duckdb.sql(
            f"SELECT COUNT(*) FROM read_parquet('{landing_dir}/loans/loans.parquet')"
        ).fetchone()[0]
        assert count == 3 * 40

    def test_performance_reads_as_hive_partitioned_dataset(self, landing_dir: Path) -> None:
        book = generate_loan_book(CONFIG)
        count = duckdb.sql(
            f"SELECT COUNT(*) FROM read_parquet("
            f"'{landing_dir}/monthly_performance/*/*.parquet', hive_partitioning = true)"
        ).fetchone()[0]
        assert count == len(book.monthly_performance)

    def test_amounts_are_exact_decimals(self, landing_dir: Path) -> None:
        column_type = duckdb.sql(
            f"SELECT typeof(principal_amount) FROM "
            f"read_parquet('{landing_dir}/loans/loans.parquet') LIMIT 1"
        ).fetchone()[0]
        assert column_type == "DECIMAL(12,2)"

    def test_principal_conservation_survives_the_round_trip(self, landing_dir: Path) -> None:
        mismatches = duckdb.sql(
            f"""
            WITH performance_totals AS (
                SELECT
                    loan_id,
                    SUM(principal_paid) AS principal_paid_total,
                    SUM(principal_writeoff) AS writeoff_total,
                    MAX_BY(ending_balance, period) AS final_balance
                FROM read_parquet(
                    '{landing_dir}/monthly_performance/*/*.parquet',
                    hive_partitioning = true
                )
                GROUP BY loan_id
            )
            SELECT COUNT(*)
            FROM read_parquet('{landing_dir}/loans/loans.parquet') AS loans
            JOIN performance_totals
                ON loans.loan_id = performance_totals.loan_id
            WHERE performance_totals.principal_paid_total
                + performance_totals.writeoff_total
                + performance_totals.final_balance
                <> loans.principal_amount
            """
        ).fetchone()[0]
        assert mismatches == 0

    def test_loans_join_borrowers_completely(self, landing_dir: Path) -> None:
        orphan_count = duckdb.sql(
            f"""
            SELECT COUNT(*)
            FROM read_parquet('{landing_dir}/loans/loans.parquet') AS loans
            LEFT JOIN read_parquet('{landing_dir}/borrowers/borrowers.parquet') AS borrowers
                ON loans.borrower_id = borrowers.borrower_id
            WHERE borrowers.borrower_id IS NULL
            """
        ).fetchone()[0]
        assert orphan_count == 0
