# ADR-0002: Loan generator — explicit state machine with monthly hazard rates

**Date:** 2026-06-10
**Status:** Accepted

## Context

Phase 1 needs a synthetic loan book that three later layers consume: the dbt
warehouse (Phase 2), the risk marts — roll rates, vintage curves, CPR/SMM
(Phase 3) — and IFRS 9 ECL (Phase 4). That forces three properties:

- **Statistical shape, not just valid rows.** Roll-rate matrices and vintage
  curves are only meaningful if delinquency transitions, prepayment, and
  default follow plausible monthly dynamics.
- **Hard invariants.** Downstream balance-reconciliation tests need cent-exact
  accounting: principal paid + write-offs must equal originated principal,
  balances must never go negative, terminal loans must emit nothing further.
- **Reproducibility.** A fixed seed must produce byte-identical parquet, so
  every downstream phase can pin its input.

The product is the correctness of the loan lifecycle — so the lifecycle model
must be the explicit, testable core, not an emergent side effect.

## Decision

A **per-loan delinquency state machine driven by calibrated monthly hazard
rates**, simulated loan by loan, month by month:

- Arrears are whole missed installments; the due-minus-paid gap maps to the
  bucket (current / 30 / 60 / 90+ / default at 4 missed, per the FFIEC
  120-day charge-off rule). The legal transition set (stay, one step deeper,
  cure to current, default absorbing) is an explicit table in
  `state_machine.py`; the simulator validates every emitted transition
  against it, so an illegal move is a crash, not a data point.
- **Post-maturity resolution.** Past maturity nothing new comes due, but the
  unpaid arrears age 30 more days each month — days past due accrue with
  calendar time on a matured balance, so the delinquency clock cannot freeze.
  Each month a matured delinquent loan either cures in full (at its bucket's
  cure probability) or rolls one bucket deeper; 90+ that fails to cure
  defaults. Hard bounds follow: a loan never stays active more than 3 months
  past maturity (worst case enters the post-maturity window at 30 dpd and
  rolls 30 → 60 → 90+ → default), and reaches a terminal state within
  3 + `recovery_lag_months` (= 9 with the default calibration) months past
  maturity. Without this rule, a loan delinquent at maturity could linger
  active indefinitely waiting on a cure draw and could never default.
- Monthly hazards (delinquency entry, cure/stay/roll, prepayment SMM) come
  from `calibration.py`, anchored to published statistics
  (docs/calibration-sources.md). Lifetime outcomes *emerge* from monthly
  dynamics rather than being sampled directly — which is exactly what makes
  roll-rate and vintage analysis on the output meaningful.
- Loan pricing adds ±150bp uniform noise to each band's anchor APR, so
  adjacent band rate ranges may overlap at the boundary (with the current
  anchors, prime_plus and super_prime overlap on 8.4–9.0%). Intentional:
  real rate sheets show cross-band dispersion from risk-based pricing
  add-ons, and a perfectly band-separable rate would be a synthetic-data
  tell.
- Accounting is integer cents on a fixed amortization schedule; the final
  installment clears the residual exactly.
- One `numpy.random.Generator` (PCG64, `default_rng(seed)`) threaded through a
  fixed iteration order gives determinism; parquet written via pyarrow is
  byte-stable for a given library version.

**Numerics stack: numpy (RNG only) + plain Python loop + pyarrow (output).**
The simulation is an inherently sequential per-loan state machine; vectorizing
it across loans (polars/pandas/numpy arrays) would contort the transition
logic that this project exists to make explicit. At Phase 1 scale (12k loans,
~215k performance rows, ~1.5 s end-to-end) a readable loop wins. pyarrow
writes the landing zone directly with exact `decimal128(12,2)` money columns —
no dataframe layer needed between dataclasses and parquet.

**Empirical calibration is a hook, not a feature.** Fitting hazards from
public loan-performance data (Fannie Mae style) is a documented interface
(`load_calibration_from_loan_performance_data`) that deliberately raises
`NotImplementedError` — the planned data sources are listed in
docs/calibration-sources.md. No fabricated "calibration that never ran".

## Alternatives considered

- **Pure random sampling of outcomes** (draw lifetime outcome per loan, then
  backfill rows). Cheapest, but monthly transitions become decorative:
  roll-rate matrices computed from the output would reflect interpolation
  artifacts, not modeled dynamics — useless for Phase 3. Lost on purpose.
- **Agent-based simulation** (borrower agents with behavioral rules and
  macro feedback). Strictly more expressive, but adds a behavior-model layer
  nobody downstream needs, is much harder to calibrate honestly against the
  published aggregates we actually have, and hides the transition rules this
  project wants to demonstrate. Lost on complexity-to-signal ratio.
- **Copying/replaying real data** (LendingClub or Fannie Mae records).
  Maximum realism, but no scenario control (cannot inject a default wave), no
  arbitrary volume, license/PII friction for a public repo, and it would gut
  the keystone signal — the generator itself. Calibrating *against* public
  data while generating synthetic rows keeps both. Lost on shareability and
  control.
- **Vectorized simulation (polars or numpy matrices).** 10–100x faster, but
  the transition logic becomes mask algebra spread across columns; the legal
  transition table can no longer reject an illegal move at the moment it
  happens. Performance is not a constraint at this scale; revisit only if
  multi-product volumes make generation a bottleneck. Lost on readability of
  the core logic.
- **Decimal/float money instead of integer cents.** Floats break exact
  reconciliation (`sum(principal) == originated`); Python `Decimal` everywhere
  is slower and noisier than int cents with a single conversion to
  `decimal128` at the parquet boundary. Lost on exactness and noise.

## Consequences

- Phase 3 risk marts can be computed directly from `monthly_performance` and
  will reconcile: every emitted transition is legal by construction, balances
  are conserved per row, and property tests pin those invariants.
- The generator is sequential; generating much larger books (multi-product,
  millions of loans) will eventually need either parallel per-cohort
  generation with spawned seed sequences or vectorization — accepted future
  cost.
- Byte-identical reproducibility is pinned to library versions (numpy bit
  stream, pyarrow writer metadata) via `uv.lock`; upgrading either may change
  bytes (not statistics) — acceptable, documented here.
- The remaining three products (mortgage, auto, cards) extend the same state
  machine with product-specific terms rather than new architectures.
