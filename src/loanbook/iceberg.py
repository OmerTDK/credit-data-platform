"""Apache Iceberg landing zone: writes the loan book as Iceberg tables.

Uses PyIceberg with a local SQLite catalog — zero external infrastructure,
runs in CI, and demonstrates real Iceberg capabilities (snapshots, time
travel, schema evolution) that the plain-parquet landing zone cannot.

The Iceberg warehouse lives at ``data/iceberg/`` (gitignored).  DuckDB 1.5.3
reads Iceberg tables via ``iceberg_scan()`` with time-travel support
(``snapshot_from_id`` / ``snapshot_from_timestamp``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pyarrow.parquet as pq
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.types import StringType

ICEBERG_WAREHOUSE_DIR = "data/iceberg"
ICEBERG_CATALOG_DB = "catalog.db"
ICEBERG_NAMESPACE = "lending"


def _catalog(warehouse_path: Path) -> SqlCatalog:
    """Create or connect to the local SQLite-backed Iceberg catalog."""
    warehouse_path.mkdir(parents=True, exist_ok=True)
    db_path = warehouse_path / ICEBERG_CATALOG_DB
    return SqlCatalog(
        "local",
        **{
            "uri": f"sqlite:///{db_path}",
            "warehouse": f"file://{warehouse_path.resolve()}",
        },
    )


def _ensure_namespace(catalog: SqlCatalog) -> None:
    """Create the lending namespace if it does not exist."""
    existing = [ns[0] for ns in catalog.list_namespaces()]
    if ICEBERG_NAMESPACE not in existing:
        catalog.create_namespace(ICEBERG_NAMESPACE)


def write_table_iceberg(
    table_name: str,
    parquet_path: Path,
    warehouse_path: Path,
) -> str:
    """Write (or overwrite) a parquet file into an Iceberg table.

    Returns the fully-qualified table name (e.g. ``lending.loans``).
    """
    catalog = _catalog(warehouse_path)
    _ensure_namespace(catalog)
    fq_name = f"{ICEBERG_NAMESPACE}.{table_name}"
    arrow_table = pq.read_table(parquet_path)

    try:
        tbl = catalog.load_table(fq_name)
        tbl.overwrite(arrow_table)
    except NoSuchTableError:
        tbl = catalog.create_table(fq_name, schema=arrow_table.schema)
        tbl.overwrite(arrow_table)
    return fq_name


def append_to_table(
    table_name: str,
    parquet_path: Path,
    warehouse_path: Path,
) -> int:
    """Append data to an existing Iceberg table, creating a new snapshot.

    Returns the new snapshot ID.  Used to demonstrate time-travel: the first
    snapshot has N rows, the second has 2N.
    """
    catalog = _catalog(warehouse_path)
    fq_name = f"{ICEBERG_NAMESPACE}.{table_name}"
    tbl = catalog.load_table(fq_name)
    arrow_table = pq.read_table(parquet_path)
    tbl.append(arrow_table)
    tbl.refresh()
    return tbl.current_snapshot().snapshot_id


def evolve_schema_add_column(
    table_name: str,
    column_name: str,
    warehouse_path: Path,
    doc: str = "",
) -> None:
    """Add a VARCHAR column to an Iceberg table — metadata-only schema evolution.

    Existing rows read NULL for the new column.  No data files are rewritten.
    """
    catalog = _catalog(warehouse_path)
    fq_name = f"{ICEBERG_NAMESPACE}.{table_name}"
    tbl = catalog.load_table(fq_name)

    with tbl.update_schema() as update:
        update.add_column(column_name, StringType(), doc=doc)


def get_snapshot_ids(
    table_name: str,
    warehouse_path: Path,
) -> list[int]:
    """Return all snapshot IDs for the given table, oldest first."""
    catalog = _catalog(warehouse_path)
    fq_name = f"{ICEBERG_NAMESPACE}.{table_name}"
    tbl = catalog.load_table(fq_name)
    snapshots = sorted(tbl.metadata.snapshots, key=lambda s: s.timestamp_ms)
    return [s.snapshot_id for s in snapshots]


def get_current_schema_field_names(
    table_name: str,
    warehouse_path: Path,
) -> list[str]:
    """Return the column names of the table's current schema."""
    catalog = _catalog(warehouse_path)
    fq_name = f"{ICEBERG_NAMESPACE}.{table_name}"
    tbl = catalog.load_table(fq_name)
    return [field.name for field in tbl.schema().fields]


def get_table_metadata_path(
    table_name: str,
    warehouse_path: Path,
) -> str:
    """Return the filesystem path to the table's current metadata.json.

    DuckDB's ``iceberg_scan()`` needs this path to read without a REST catalog.
    """
    catalog = _catalog(warehouse_path)
    fq_name = f"{ICEBERG_NAMESPACE}.{table_name}"
    tbl = catalog.load_table(fq_name)
    return tbl.metadata_location
