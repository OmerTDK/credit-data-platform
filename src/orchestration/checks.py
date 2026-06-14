"""Quality-gate logic for the credit-data-platform Dagster assets.

Each function is a pure query over the built DuckDB warehouse, returning a
:class:`CheckOutcome`. Keeping the logic here (rather than inline in the
@asset_check bodies) makes every gate independently unit-testable and
kill-testable without spinning up a Dagster run — see
tests/test_orchestration_checks.py.

The gates encode invariants that generic dbt not_null/unique tests cannot:

* Stage 1 / Stage 2 ECL strictly positive at portfolio level — a performing
  loan book MUST carry a non-zero loss allowance. If a PD term-structure change
  drives Stage 1 PDs to zero, the allowance collapses; this gate catches it.
* Referential integrity facts -> dims — every fact loan_id resolves to dim_loan.
* Volume sanity on the ECL allowance mart — row count within an expected band.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

# mart_finance_ecl_allowance holds one row per (loan, scenario): 12,000 loans x
# 4 scenarios (baseline / adverse / upside / probability_weighted) = 48,000.
# The band tolerates moderate changes in generated volume without going silent.
ECL_ALLOWANCE_MIN_ROWS = 20_000
ECL_ALLOWANCE_MAX_ROWS = 120_000

# Loan-grained relations whose loan_id must resolve to dim_loan. Fixed allowlist —
# never user input — which is why the f-string interpolation in _orphan_count is
# safe (a value outside this set raises before any SQL is built).
LOAN_FACT_RELATIONS = (
    "dwh.fct_payment",
    "dwh.fct_loan_state_event",
    "mart_finance.mart_finance_ecl_allowance",
)


@dataclass(frozen=True)
class CheckOutcome:
    """Result of a single quality gate."""

    passed: bool
    metadata: dict[str, Any] = field(default_factory=dict)


def _query_one(warehouse: Path, sql: str) -> tuple[Any, ...]:
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        row = connection.execute(sql).fetchone()
    if row is None:
        raise LookupError(f"query returned no rows: {sql}")
    return row


def check_ecl_stage_ecl_positive(warehouse: Path) -> CheckOutcome:
    """Stage 1 and Stage 2 ECL must be strictly positive in every scenario.

    Evaluated at the summary-mart grain (one row per segment x scenario). The
    minimum per-scenario stage total across the whole portfolio must exceed zero;
    a single scenario collapsing to zero allowance fails the gate.
    """
    stage1_min, stage2_min = _per_scenario_stage_minima(warehouse)
    passed = stage1_min > 0 and stage2_min > 0
    return CheckOutcome(
        passed=passed,
        metadata={
            "min_stage1_ecl": stage1_min,
            "min_stage2_ecl": stage2_min,
            "rule": "min per-scenario Stage 1 and Stage 2 total ECL > 0",
        },
    )


def _per_scenario_stage_minima(warehouse: Path) -> tuple[float, float]:
    sql = """
        with by_scenario_stage as (
            select
                scenario_name,
                ifrs9_stage,
                sum(total_ecl_amount) as stage_ecl
            from mart_finance.mart_finance_ecl_summary
            group by scenario_name, ifrs9_stage
        )
        select
            cast(coalesce(min(stage_ecl) filter (where ifrs9_stage = 1), 0) as double),
            cast(coalesce(min(stage_ecl) filter (where ifrs9_stage = 2), 0) as double)
        from by_scenario_stage
    """
    stage1_min, stage2_min = _query_one(warehouse, sql)
    return float(stage1_min), float(stage2_min)


def check_referential_integrity_facts_to_dims(warehouse: Path) -> CheckOutcome:
    """Every fact loan_id must resolve to a dim_loan row.

    Covers the three loan-grained facts/marts that carry a loan_id foreign key:
    fct_payment, fct_loan_state_event, and mart_finance_ecl_allowance.
    """
    counts = {
        relation.split(".")[-1]: _orphan_count(warehouse, relation)
        for relation in LOAN_FACT_RELATIONS
    }
    orphan_total = sum(counts.values())
    return CheckOutcome(
        passed=orphan_total == 0,
        metadata={"orphan_rows_total": orphan_total, "orphans_by_relation": counts},
    )


def _orphan_count(warehouse: Path, relation: str) -> int:
    if relation not in LOAN_FACT_RELATIONS:
        raise ValueError(f"unknown loan-fact relation: {relation!r}")
    # relation is allowlisted above (never user input), so the interpolation is safe.
    sql = f"""
        select cast(count(*) as bigint)
        from {relation} as fact
        left join dwh.dim_loan as dim
            on fact.loan_id = dim.loan_id
        where dim.loan_id is null
    """  # nosec B608
    return int(_query_one(warehouse, sql)[0])


def check_volume_sanity_ecl_allowance(warehouse: Path) -> CheckOutcome:
    """ECL allowance row count must sit within the expected volume band."""
    row_count = int(
        _query_one(
            warehouse,
            "select cast(count(*) as bigint) from mart_finance.mart_finance_ecl_allowance",
        )[0]
    )
    passed = ECL_ALLOWANCE_MIN_ROWS <= row_count <= ECL_ALLOWANCE_MAX_ROWS
    return CheckOutcome(
        passed=passed,
        metadata={
            "row_count": row_count,
            "expected_min": ECL_ALLOWANCE_MIN_ROWS,
            "expected_max": ECL_ALLOWANCE_MAX_ROWS,
        },
    )
