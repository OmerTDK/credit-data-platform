# ADR-0005: Dimensional layer and event-sourced loan state

**Date:** 2026-06-14
**Status:** Accepted

## Context

Phase 2b builds the DWH layer on top of the Phase 2a staging views. Six structural choices
are forced before the first model exists:

1. **What time-varying attribute to use for SCD2 on dim_borrower.** The borrower table in the
   landing zone is a static snapshot: one row per borrower at origination. Static attributes
   (age band, income band, region, score band, credit score) never change in the generator.
   Modeling SCD2 over a frozen snapshot yields a trivially-single-version dimension with no
   analytical value — it cannot answer "what did this borrower look like on date X" because
   there is nothing that varies over X.

2. **How to represent loan state changes** — as a mutable overwritten status column vs. an
   immutable event stream.

3. **How to compute current state** — by storing it redundantly on the fact, or deriving it
   from the event stream.

4. **How to model loan lifecycle milestones** — as sparse columns on multiple facts, or as an
   accumulating snapshot.

5. **How to assign surrogate keys** — MD5 hash vs. sequence / identity.

6. **How to build the date dimension** without dbt_utils (not a project dependency).

## Decision

### 1. SCD2 attribute for dim_borrower: derived worst delinquency bucket

The landing zone has no time-varying borrower attributes. Rather than ship a tautological
one-version SCD2 (all borrowers, all time = version 1), the derived attribute
`current_delinquency_bucket` is computed from the monthly performance stream via
`int_borrower_monthly_delinquency`: for each borrower and each reporting month, take the
worst delinquency bucket across all of that borrower's active loans (severity order: default >
dpd_90_plus > dpd_60 > dpd_30 > current).

This attribute genuinely varies over time — 2,323 of 12,000 loans enter delinquency in the
generated book, producing SCD2 transitions. The result: 19,257 version rows across 12,000
borrowers, with up to 12 versions per borrower for a heavily delinquent borrower.

**Why this instead of a one-version SCD2:**
A one-version SCD2 is structurally correct but analytically empty — no query benefits from
joining to it. The derived attribute makes SCD2 meaningful for the portfolio's risk narrative:
"how many borrowers have entered delinquency at any given point in time?"

**Why not a tautological SCD2 with a comment:**
Documenting an architectural pattern that produces no analytical value signals the wrong thing
for a portfolio platform. The pattern must be demonstrated on a genuinely time-varying
attribute. The derivation is clearly documented in this ADR and in the model description.

**What happens when the generator adds time-varying borrower attributes:**
The model is keyed correctly (`borrower_id`, `version_number`) and will absorb additional
SCD2 attributes in the `change_detection` CTE without structural change.

**Open question (flagged for Omer's review):** The derived attribute is "worst delinquency
bucket across the borrower's loans this month." For a borrower with multiple loans (the
generator currently produces 1:1 borrower-to-loan), this aggregates across loans. If the
generator later allows one borrower to carry more than one loan, the SCD2 semantics remain
correct: worst-bucket across all loans is still a meaningful borrower-level risk signal.

### 2. Loan state as event sourcing

`fct_loan_state_event` is an immutable append-only table of state-change events derived from
the monthly performance stream. One row per event: origination (period 1 of every loan),
delinquency_transition (delinquency_bucket changes), and lifecycle_transition (loan_status
reaches a terminal state). Events are never updated or deleted.

**Why event sourcing instead of a mutable status column:**
- **Point-in-time correctness.** Any query that joins to the event stream with a date filter
  recovers the exact state of any loan on any historical date. A mutable column loses this
  forever the moment it is overwritten.
- **Auditability.** The event stream is its own audit log: every state transition, its cause,
  and its timing are first-class data.
- **Derived current state is verifiable.** A test (`assert_dwh_current_state_matches_event_stream`)
  computes current state independently (MAX months_on_book from the performance table) and
  asserts it equals the event-stream-derived view. This is impossible to test when current
  state is stored directly — you would be comparing a column to itself.

**Why event sourcing over snapshots:**
A daily snapshot would store one row per loan per snapshot date. At 12,000 loans × 35 months
× 30 days that is 12.6 million rows for identical data. Events at 21,320 rows are 600x
smaller and richer.

**Trade-off:** Computing current state requires a MAX window function over the event stream.
`dim_loan_current_state` pre-computes this as a table to avoid re-running the window on every
query. The pre-computation adds one model and is refreshed on every dbt run.

### 3. Current state derived from the event stream

`dim_loan_current_state` is a table model derived from `fct_loan_state_event` by selecting
the event with the highest `months_on_book` per loan. It is explicitly documented as derived,
not authoritative — the event stream is the source of truth.

A dbt custom test (`assert_dwh_current_state_matches_event_stream`) verifies that the derived
current state matches a direct independent computation from `int_monthly_performance`. If the
derivation logic were wrong, this test would catch it.

### 4. Loan lifecycle milestones as accumulating snapshot

`fct_loan_lifecycle` is an accumulating snapshot fact: one row per loan, with milestone
date columns that fill in as the loan passes through its lifecycle. Milestones: origination,
first payment, first 30/60/90-day delinquency, default, payoff/prepayment, recovery
completion.

**Why accumulating snapshot:**
The loan lifecycle is a natural sequence of milestones with a fixed set of "phases." Milestone
delay analysis (time from origination to first delinquency, time from default to recovery
completion) is natural when all milestones are on one row. The alternative — a separate fact
row per milestone — requires a self-join or pivot for any milestone-to-milestone duration
query. Accumulating snapshot is the established pattern for this use case (Kimball Data
Warehouse Toolkit, Ch. 6).

**Grain:** one row per loan (loan_id). The row is logically updated as new milestones are
reached, but in practice `dbt run` replaces the table on each run, so the model is always
current as of the last run.

**Custom tests:** `assert_dwh_lifecycle_milestone_order` verifies milestone ordering
invariants (first_dpd60 cannot precede first_dpd30; default cannot precede first_dpd90).

### 5. Surrogate keys: MD5 hash over natural key

All surrogate keys are MD5 hashes of the natural key (or a concatenation for compound keys),
produced by the `generate_surrogate_key` macro. MD5 is deterministic, platform-independent,
and needs no sequence state — the same loan_id always produces the same loan_key on every
run and on every target (DuckDB dev, BigQuery prod).

**Trade-off:** MD5 collision probability is negligible at this scale (12,000 loans, 4
products), but theoretically non-zero. For production at much larger scale, a sequence-keyed
surrogate would be safer but requires target-specific sequence support. The MD5 approach is
correct for a dual-target (DuckDB/BigQuery) platform at this volume.

### 6. Date dimension: manual date spine without dbt_utils

`dim_date` generates its date spine using DuckDB's `unnest(range(...))` function in a `numbers`
CTE, then derives calendar attributes with DuckDB's `strftime` and `extract` functions.
dbt_utils was not added as a package dependency because it adds a dependency-management
surface (version pinning, package resolution) for a single macro that a 12-line CTE replaces.

**Trade-off:** the date spine is DuckDB-specific syntax. When the BigQuery prod target is
enabled (ADR-0001), this CTE must become target-aware (`GENERATE_DATE_ARRAY` in BigQuery vs.
`unnest(range(...))` in DuckDB), or dbt_utils should be added at that point and the manual
spine replaced. Accepted open item, consistent with ADR-0001's deferral of BigQuery-specific
syntax.

## Alternatives considered

### SCD2 borrower dimension without a time-varying attribute
Ship SCD2 with only the static origination attributes (credit score, age band, etc.) — every
borrower has exactly one version. Structurally correct. Analytically empty: no query benefits
from the SCD2 wrapper over a simple static dim. Rejected: demonstrates the SCD2 pattern in
name only, not in substance.

### Mutable loan status column
Store `current_loan_status` and `current_delinquency_bucket` as columns updated in place on a
`dim_loan` or `fct_loan_current` table. Rejected: (a) dbt's `table` materialization replaces
the entire table on each run — there is no "in place update" in dbt without `incremental`
strategy, (b) even with incremental, you lose the history of what the status was before the
update, (c) the test that verifies event-stream correctness cannot be written — you would be
comparing a derived column to itself.

### Snapshot-based current state (one row per loan per run date)
Use a dbt snapshot to capture daily state. 12,000 loans × ~900 run days (3 years at daily
runs) = 10.8 million rows of duplicated data, 99.9% of which is unchanged from the prior run.
Rejected on volume: event sourcing achieves the same auditability in 21,320 rows (1,800x
fewer) and is recomputed from the performance stream on every run without needing SCD2
bookkeeping at the snapshot layer.

### Separate milestone facts
A separate row per milestone (origination, default, payoff, ...) in a single `fct_milestone`
table. Rejected: any milestone-duration query requires a self-join or pivot on milestone_type.
The accumulating snapshot pattern removes the self-join by putting all milestones on one row,
at the cost of nullable milestone columns for loans that have not yet reached that stage.

## Consequences

- `dim_borrower`'s time-varying attribute is derived, not sourced directly. A change to the
  generator that adds native borrower attributes (income changes, address changes) will require
  extending `int_borrower_monthly_delinquency` to join those attributes in, or adding a
  second SCD2 tracked column. This is an additive change, not a breaking one.
- `dim_loan_current_state` is a derived view pre-computed as a table. It is refreshed on
  every `dbt run`. Between runs, it reflects the state from the last run, not the latest
  upstream data — correct for a batch pipeline, but not for real-time consumption.
- The date spine is DuckDB-only. BigQuery prod target requires a syntax change or dbt_utils
  addition (ADR-0001 deferral).
- Event sourcing produces a `fct_loan_state_event` that is larger than a simple status
  column but much smaller than a daily snapshot. It is the foundation Phase 3 risk marts
  (roll-rate matrices, vintage curves) will query directly for transition counting.

## Grain summary

| Model | Grain |
|-------|-------|
| `dim_date` | One row per calendar day (2020-01-01 to 2029-12-31) |
| `dim_product` | One row per credit product type (4 rows: personal_loan, auto_loan, mortgage, credit_card) |
| `dim_loan` | One row per originated loan account |
| `dim_borrower` | One row per (borrower_id, SCD2 version) — version boundary = change in current_delinquency_bucket |
| `dim_loan_current_state` | One row per loan (current state only, derived from event stream) |
| `fct_loan_origination` | One row per originated loan at origination |
| `fct_payment` | One row per loan per month on book (loan_id, months_on_book) |
| `fct_loan_state_event` | One row per loan state-change event (loan_id, months_on_book, event_type) |
| `fct_loan_lifecycle` | One row per loan (accumulating snapshot of lifecycle milestones) |
