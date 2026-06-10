"""Parquet landing-zone writer: deterministic files DuckDB reads directly.

Monthly performance is hive-partitioned by report month. The partition key is
named report_year_month (not report_month) on purpose: DuckDB shadows an
in-file column with the partition value on a name collision, which would
silently turn the DATE column into a VARCHAR.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from loanbook.borrowers import Borrower
from loanbook.generate import LoanBook
from loanbook.loans import Loan
from loanbook.performance import MonthlyPerformance

MONEY_DECIMAL_DIGITS = 12
MONEY_SCALE = 2
MONEY_TYPE = pa.decimal128(MONEY_DECIMAL_DIGITS, MONEY_SCALE)
PARQUET_COMPRESSION = "zstd"

LOANS_FILE = "loans/loans.parquet"
BORROWERS_FILE = "borrowers/borrowers.parquet"
PERFORMANCE_DIR = "monthly_performance"


def write_loan_book(book: LoanBook, landing_dir: Path) -> list[Path]:
    """Write the book to the landing zone; returns the files written."""
    written_files = [
        _write_table(_borrowers_table(book.borrowers), landing_dir / BORROWERS_FILE),
        _write_table(_loans_table(book.loans), landing_dir / LOANS_FILE),
    ]
    written_files.extend(_write_performance_partitions(book.monthly_performance, landing_dir))
    return written_files


def _write_table(table: pa.Table, target_file: Path) -> Path:
    target_file.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, target_file, compression=PARQUET_COMPRESSION)
    return target_file


def _write_performance_partitions(rows: list[MonthlyPerformance], landing_dir: Path) -> list[Path]:
    rows_by_month: dict[date, list[MonthlyPerformance]] = {}
    for row in rows:
        rows_by_month.setdefault(row.report_month, []).append(row)
    written_files = []
    for report_month in sorted(rows_by_month):
        partition_name = f"report_year_month={report_month.strftime('%Y-%m')}"
        target_file = landing_dir / PERFORMANCE_DIR / partition_name / "rows.parquet"
        written_files.append(
            _write_table(_performance_table(rows_by_month[report_month]), target_file)
        )
    return written_files


def _money(cents_values: list[int | None]) -> pa.Array:
    return pa.array(
        [
            Decimal(cents).scaleb(-MONEY_SCALE) if cents is not None else None
            for cents in cents_values
        ],
        type=MONEY_TYPE,
    )


def _borrowers_table(borrowers: list[Borrower]) -> pa.Table:
    return pa.table(
        {
            "borrower_id": pa.array([b.borrower_id for b in borrowers], type=pa.string()),
            "age_band": pa.array([b.age_band for b in borrowers], type=pa.string()),
            "income_band": pa.array([b.income_band for b in borrowers], type=pa.string()),
            "region": pa.array([b.region for b in borrowers], type=pa.string()),
            "score_band": pa.array([b.score_band for b in borrowers], type=pa.string()),
            "credit_score": pa.array([b.credit_score for b in borrowers], type=pa.int16()),
        }
    )


def _loans_table(loans: list[Loan]) -> pa.Table:
    return pa.table(
        {
            "loan_id": pa.array([loan.loan_id for loan in loans], type=pa.string()),
            "borrower_id": pa.array([loan.borrower_id for loan in loans], type=pa.string()),
            "product_type": pa.array([loan.product_type for loan in loans], type=pa.string()),
            "origination_month": pa.array(
                [loan.origination_month for loan in loans], type=pa.date32()
            ),
            "principal_amount": _money([loan.principal_cents for loan in loans]),
            "term_months": pa.array([loan.term_months for loan in loans], type=pa.int16()),
            "interest_rate": pa.array([loan.interest_rate for loan in loans], type=pa.float64()),
            "monthly_payment": _money([loan.monthly_payment_cents for loan in loans]),
            "credit_limit": _money([loan.credit_limit_cents for loan in loans]),
            "score_band": pa.array([loan.score_band for loan in loans], type=pa.string()),
        }
    )


def _performance_table(rows: list[MonthlyPerformance]) -> pa.Table:
    return pa.table(
        {
            "loan_id": pa.array([row.loan_id for row in rows], type=pa.string()),
            "product_type": pa.array([row.product_type for row in rows], type=pa.string()),
            "period": pa.array([row.period for row in rows], type=pa.int16()),
            "report_month": pa.array([row.report_month for row in rows], type=pa.date32()),
            "beginning_balance": _money([row.beginning_balance_cents for row in rows]),
            "draw_amount": _money([row.draw_cents for row in rows]),
            "scheduled_payment": _money([row.scheduled_payment_cents for row in rows]),
            "actual_payment": _money([row.actual_payment_cents for row in rows]),
            "principal_paid": _money([row.principal_paid_cents for row in rows]),
            "interest_paid": _money([row.interest_paid_cents for row in rows]),
            "interest_charged": _money([row.interest_charged_cents for row in rows]),
            "ending_balance": _money([row.ending_balance_cents for row in rows]),
            "principal_writeoff": _money([row.principal_writeoff_cents for row in rows]),
            "recovery_amount": _money([row.recovery_cents for row in rows]),
            "utilization": pa.array([row.utilization for row in rows], type=pa.float64()),
            "delinquency_bucket": pa.array(
                [row.delinquency_bucket.value for row in rows], type=pa.string()
            ),
            "loan_status": pa.array([row.loan_status.value for row in rows], type=pa.string()),
            "is_prepayment": pa.array([row.is_prepayment for row in rows], type=pa.bool_()),
        }
    )
