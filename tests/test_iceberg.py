"""Tests for the Apache Iceberg integration.

Exercises real Iceberg capabilities — not stubs:
  - Write parquet data into Iceberg tables via PyIceberg (SQLite catalog)
  - Time travel: query historical snapshots through DuckDB's iceberg_scan()
  - Schema evolution: add a column metadata-only, verify DuckDB reads NULLs
  - Snapshot inspection: list snapshots, verify counts
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from loanbook.iceberg import (
    append_to_table,
    evolve_schema_add_column,
    get_current_schema_field_names,
    get_snapshot_ids,
    get_table_metadata_path,
    write_table_iceberg,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LANDING_DIR = REPO_ROOT / "data" / "landing"
LOANS_PARQUET = LANDING_DIR / "loans" / "loans.parquet"
BORROWERS_PARQUET = LANDING_DIR / "borrowers" / "borrowers.parquet"


@pytest.fixture()
def iceberg_warehouse(tmp_path: Path) -> Path:
    """Provide a fresh temporary Iceberg warehouse directory."""
    wh = tmp_path / "iceberg"
    wh.mkdir()
    return wh


@pytest.fixture()
def duckdb_conn() -> duckdb.DuckDBPyConnection:
    """A DuckDB connection with the Iceberg extension loaded."""
    conn = duckdb.connect()
    conn.execute("INSTALL iceberg; LOAD iceberg;")
    return conn


# ---------------------------------------------------------------------------
# Pre-condition: the landing-zone parquet must exist (``make generate``).
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _require_landing_zone() -> None:
    if not LOANS_PARQUET.exists():
        pytest.skip("Landing zone not generated — run `make generate` first")


# ---------------------------------------------------------------------------
# Write & read
# ---------------------------------------------------------------------------
class TestIcebergWrite:
    """Writing parquet data into Iceberg tables."""

    def test_write_loans_creates_table(self, iceberg_warehouse: Path) -> None:
        name = write_table_iceberg("loans", LOANS_PARQUET, iceberg_warehouse)
        assert name == "lending.loans"
        assert len(get_snapshot_ids("loans", iceberg_warehouse)) >= 1

    def test_write_borrowers_creates_table(self, iceberg_warehouse: Path) -> None:
        name = write_table_iceberg("borrowers", BORROWERS_PARQUET, iceberg_warehouse)
        assert name == "lending.borrowers"
        assert len(get_snapshot_ids("borrowers", iceberg_warehouse)) >= 1

    def test_duckdb_reads_iceberg_loans(
        self, iceberg_warehouse: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        write_table_iceberg("loans", LOANS_PARQUET, iceberg_warehouse)
        meta = get_table_metadata_path("loans", iceberg_warehouse)
        row_count = duckdb_conn.execute(f"SELECT count(*) FROM iceberg_scan('{meta}')").fetchone()[
            0
        ]
        assert row_count == 12_000

    def test_duckdb_reads_iceberg_borrowers(
        self, iceberg_warehouse: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        write_table_iceberg("borrowers", BORROWERS_PARQUET, iceberg_warehouse)
        meta = get_table_metadata_path("borrowers", iceberg_warehouse)
        row_count = duckdb_conn.execute(f"SELECT count(*) FROM iceberg_scan('{meta}')").fetchone()[
            0
        ]
        assert row_count == 12_000

    def test_overwrite_is_idempotent(self, iceberg_warehouse: Path) -> None:
        """Calling write twice overwrites rather than appending."""
        write_table_iceberg("loans", LOANS_PARQUET, iceberg_warehouse)
        write_table_iceberg("loans", LOANS_PARQUET, iceberg_warehouse)
        # Should still be exactly one snapshot's-worth of rows (overwrite, not append)
        meta = get_table_metadata_path("loans", iceberg_warehouse)
        conn = duckdb.connect()
        conn.execute("INSTALL iceberg; LOAD iceberg;")
        row_count = conn.execute(f"SELECT count(*) FROM iceberg_scan('{meta}')").fetchone()[0]
        assert row_count == 12_000


# ---------------------------------------------------------------------------
# Time travel
# ---------------------------------------------------------------------------
class TestTimeTravel:
    """DuckDB ``iceberg_scan(snapshot_from_id=...)`` queries historical state."""

    def test_time_travel_row_count(
        self, iceberg_warehouse: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        """Snapshot 1 has 12K rows; after append, snapshot 2 has 24K.
        Time-traveling to snapshot 1 returns 12K.
        """
        write_table_iceberg("loans", LOANS_PARQUET, iceberg_warehouse)
        snap_ids_before = get_snapshot_ids("loans", iceberg_warehouse)
        assert len(snap_ids_before) >= 1
        first_snapshot_id = snap_ids_before[0]

        # Append creates a second snapshot
        append_to_table("loans", LOANS_PARQUET, iceberg_warehouse)
        snap_ids_after = get_snapshot_ids("loans", iceberg_warehouse)
        assert len(snap_ids_after) >= 2

        meta = get_table_metadata_path("loans", iceberg_warehouse)

        # Current state: 24K rows (12K + 12K appended)
        current = duckdb_conn.execute(f"SELECT count(*) FROM iceberg_scan('{meta}')").fetchone()[0]
        assert current == 24_000

        # Time travel to first snapshot: 12K rows
        historical = duckdb_conn.execute(
            f"SELECT count(*) FROM iceberg_scan('{meta}', snapshot_from_id = {first_snapshot_id})"
        ).fetchone()[0]
        assert historical == 12_000

    def test_time_travel_preserves_data_integrity(
        self, iceberg_warehouse: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        """Historical snapshot returns the same loan IDs as the original write."""
        write_table_iceberg("loans", LOANS_PARQUET, iceberg_warehouse)
        first_snap = get_snapshot_ids("loans", iceberg_warehouse)[0]

        # Capture original loan_id set
        meta = get_table_metadata_path("loans", iceberg_warehouse)
        original_ids = {
            r[0]
            for r in duckdb_conn.execute(f"SELECT loan_id FROM iceberg_scan('{meta}')").fetchall()
        }

        # Append and time-travel back
        append_to_table("loans", LOANS_PARQUET, iceberg_warehouse)
        meta = get_table_metadata_path("loans", iceberg_warehouse)
        historical_ids = {
            r[0]
            for r in duckdb_conn.execute(
                f"SELECT loan_id FROM iceberg_scan('{meta}', snapshot_from_id = {first_snap})"
            ).fetchall()
        }
        assert original_ids == historical_ids


# ---------------------------------------------------------------------------
# Schema evolution
# ---------------------------------------------------------------------------
class TestSchemaEvolution:
    """Iceberg metadata-only schema evolution (add column)."""

    def test_add_column_appears_in_schema(self, iceberg_warehouse: Path) -> None:
        write_table_iceberg("borrowers", BORROWERS_PARQUET, iceberg_warehouse)
        cols_before = get_current_schema_field_names("borrowers", iceberg_warehouse)
        assert "risk_tier" not in cols_before

        evolve_schema_add_column(
            "borrowers", "risk_tier", iceberg_warehouse, doc="Derived risk tier"
        )
        cols_after = get_current_schema_field_names("borrowers", iceberg_warehouse)
        assert "risk_tier" in cols_after

    def test_evolved_column_reads_null_in_duckdb(
        self, iceberg_warehouse: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        """Existing rows return NULL for the newly added column."""
        write_table_iceberg("borrowers", BORROWERS_PARQUET, iceberg_warehouse)
        evolve_schema_add_column(
            "borrowers", "risk_tier", iceberg_warehouse, doc="Derived risk tier"
        )

        meta = get_table_metadata_path("borrowers", iceberg_warehouse)
        # DuckDB sees the evolved schema
        col_names = [
            r[0]
            for r in duckdb_conn.execute(
                f"SELECT column_name FROM (DESCRIBE SELECT * FROM iceberg_scan('{meta}'))"
            ).fetchall()
        ]
        assert "risk_tier" in col_names

        # All existing rows have NULL for the new column
        null_count = duckdb_conn.execute(
            f"SELECT count(*) FROM iceberg_scan('{meta}') WHERE risk_tier IS NULL"
        ).fetchone()[0]
        total = duckdb_conn.execute(f"SELECT count(*) FROM iceberg_scan('{meta}')").fetchone()[0]
        assert null_count == total
        assert total == 12_000

    def test_schema_evolution_is_metadata_only(self, iceberg_warehouse: Path) -> None:
        """Adding a column does NOT create a new data snapshot."""
        write_table_iceberg("borrowers", BORROWERS_PARQUET, iceberg_warehouse)
        snaps_before = get_snapshot_ids("borrowers", iceberg_warehouse)
        evolve_schema_add_column(
            "borrowers", "risk_tier", iceberg_warehouse, doc="Derived risk tier"
        )
        snaps_after = get_snapshot_ids("borrowers", iceberg_warehouse)
        # Same snapshots — schema evolution is metadata-only
        assert snaps_before == snaps_after


# ---------------------------------------------------------------------------
# Snapshot inspection
# ---------------------------------------------------------------------------
class TestSnapshotInspection:
    """iceberg_snapshots() from DuckDB returns snapshot metadata."""

    def test_duckdb_iceberg_snapshots(
        self, iceberg_warehouse: Path, duckdb_conn: duckdb.DuckDBPyConnection
    ) -> None:
        write_table_iceberg("loans", LOANS_PARQUET, iceberg_warehouse)
        append_to_table("loans", LOANS_PARQUET, iceberg_warehouse)

        meta = get_table_metadata_path("loans", iceberg_warehouse)
        snapshots = duckdb_conn.execute(f"SELECT * FROM iceberg_snapshots('{meta}')").fetchall()
        assert len(snapshots) >= 2
