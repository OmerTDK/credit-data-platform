"""Tests for parquet landing-zone output: layout, types, and DuckDB readability."""

from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
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

MONEY = pa.decimal128(12, 2)

EXPECTED_BORROWERS_SCHEMA = pa.schema(
    [
        ("borrower_id", pa.string()),
        ("age_band", pa.string()),
        ("income_band", pa.string()),
        ("region", pa.string()),
        ("score_band", pa.string()),
        ("credit_score", pa.int16()),
    ]
)

EXPECTED_LOANS_SCHEMA = pa.schema(
    [
        ("loan_id", pa.string()),
        ("borrower_id", pa.string()),
        ("product_type", pa.string()),
        ("origination_month", pa.date32()),
        ("principal_amount", MONEY),
        ("term_months", pa.int16()),
        ("interest_rate", pa.float64()),
        ("monthly_payment", MONEY),
        ("credit_limit", MONEY),
        ("score_band", pa.string()),
    ]
)

EXPECTED_PERFORMANCE_SCHEMA = pa.schema(
    [
        ("loan_id", pa.string()),
        ("product_type", pa.string()),
        ("period", pa.int16()),
        ("report_month", pa.date32()),
        ("beginning_balance", MONEY),
        ("draw_amount", MONEY),
        ("scheduled_payment", MONEY),
        ("actual_payment", MONEY),
        ("principal_paid", MONEY),
        ("interest_paid", MONEY),
        ("interest_charged", MONEY),
        ("ending_balance", MONEY),
        ("principal_writeoff", MONEY),
        ("recovery_amount", MONEY),
        ("utilization", pa.float64()),
        ("delinquency_bucket", pa.string()),
        ("loan_status", pa.string()),
        ("is_prepayment", pa.bool_()),
    ]
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


class TestPinnedSchemas:
    """Dropping, reordering, renaming, or retyping a landing column must fail here."""

    def test_borrowers_schema_is_pinned(self, landing_dir: Path) -> None:
        written = pq.read_schema(landing_dir / "borrowers" / "borrowers.parquet")
        assert written.equals(EXPECTED_BORROWERS_SCHEMA), (
            f"borrowers schema drifted:\n{written}\nexpected:\n{EXPECTED_BORROWERS_SCHEMA}"
        )

    def test_loans_schema_is_pinned(self, landing_dir: Path) -> None:
        written = pq.read_schema(landing_dir / "loans" / "loans.parquet")
        assert written.equals(EXPECTED_LOANS_SCHEMA), (
            f"loans schema drifted:\n{written}\nexpected:\n{EXPECTED_LOANS_SCHEMA}"
        )

    def test_every_performance_partition_schema_is_pinned(self, landing_dir: Path) -> None:
        partition_files = sorted((landing_dir / "monthly_performance").glob("*/rows.parquet"))
        assert partition_files
        for partition_file in partition_files:
            written = pq.read_schema(partition_file)
            assert written.equals(EXPECTED_PERFORMANCE_SCHEMA), (
                f"monthly_performance schema drifted in {partition_file.parent.name}:\n"
                f"{written}\nexpected:\n{EXPECTED_PERFORMANCE_SCHEMA}"
            )


class TestProductFieldNullability:
    def test_cards_carry_limits_and_no_amortizing_fields(self, landing_dir: Path) -> None:
        violation_count = duckdb.sql(
            f"""
            SELECT COUNT(*)
            FROM read_parquet('{landing_dir}/loans/loans.parquet')
            WHERE product_type = 'credit_card'
              AND (
                credit_limit IS NULL
                OR principal_amount IS NOT NULL
                OR term_months IS NOT NULL
                OR monthly_payment IS NOT NULL
              )
            """
        ).fetchone()[0]
        assert violation_count == 0

    def test_amortizing_loans_carry_terms_and_no_credit_limit(self, landing_dir: Path) -> None:
        violation_count = duckdb.sql(
            f"""
            SELECT COUNT(*)
            FROM read_parquet('{landing_dir}/loans/loans.parquet')
            WHERE product_type <> 'credit_card'
              AND (
                credit_limit IS NOT NULL
                OR principal_amount IS NULL
                OR term_months IS NULL
                OR monthly_payment IS NULL
              )
            """
        ).fetchone()[0]
        assert violation_count == 0

    def test_utilization_is_card_only(self, landing_dir: Path) -> None:
        violation_count = duckdb.sql(
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{landing_dir}/monthly_performance/*/*.parquet', hive_partitioning = true
            )
            WHERE (product_type = 'credit_card' AND utilization IS NULL)
               OR (product_type <> 'credit_card' AND utilization IS NOT NULL)
            """
        ).fetchone()[0]
        assert violation_count == 0

    def test_every_product_lands_in_both_tables(self, landing_dir: Path) -> None:
        loan_products = {
            row[0]
            for row in duckdb.sql(
                f"SELECT DISTINCT product_type "
                f"FROM read_parquet('{landing_dir}/loans/loans.parquet')"
            ).fetchall()
        }
        performance_products = {
            row[0]
            for row in duckdb.sql(
                f"SELECT DISTINCT product_type FROM read_parquet("
                f"'{landing_dir}/monthly_performance/*/*.parquet', hive_partitioning = true)"
            ).fetchall()
        }
        expected = {"personal_loan", "auto_loan", "mortgage", "credit_card"}
        assert loan_products == expected
        assert performance_products == expected


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

    def test_amortizing_principal_conservation_survives_the_round_trip(
        self, landing_dir: Path
    ) -> None:
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
            WHERE loans.product_type <> 'credit_card'
              AND performance_totals.principal_paid_total
                + performance_totals.writeoff_total
                + performance_totals.final_balance
                <> loans.principal_amount
            """
        ).fetchone()[0]
        assert mismatches == 0

    def test_universal_balance_identity_survives_the_round_trip(self, landing_dir: Path) -> None:
        mismatches = duckdb.sql(
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{landing_dir}/monthly_performance/*/*.parquet', hive_partitioning = true
            )
            WHERE ending_balance <> beginning_balance
                + draw_amount
                + interest_charged
                - interest_paid
                - principal_paid
                - principal_writeoff
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
