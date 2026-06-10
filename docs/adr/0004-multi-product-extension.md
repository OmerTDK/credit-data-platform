# ADR-0004: Multi-product extension — one schema, one state machine, an explicit revolving model

**Date:** 2026-06-10
**Status:** Accepted (extends ADR-0002)

## Context

ADR-0002 shipped the generator for personal loans and anticipated the
extension: "the remaining three products (mortgage, auto, cards) extend the
same state machine with product-specific terms rather than new
architectures." Phase 2b makes that real. Three design questions had to be
settled:

1. **Where do amortizing products differ?** Auto loans and mortgages share
   the personal-loan lifecycle (fixed schedule, arrears in whole
   installments, post-maturity resolution) but differ in every parameter:
   term structure, amount distribution, pricing, hazards, recovery.
2. **What does a revolving product even look like here?** Cards have no
   principal, no term, no maturity, no amortization schedule — none of the
   machinery the loan simulator is built on.
3. **One landing schema or per-product tables?** Downstream dbt (Phase 2)
   builds staging and dimensional models on the landing zone; the schema
   decision shapes every later layer.

This is a new decision record rather than an amendment inside ADR-0002
because ADR-0002's decision — explicit state machine driven by calibrated
monthly hazards — is unchanged and remains accurate as written. What follows
are new decisions layered on top of it; rewriting history inside an accepted
ADR would hide which choices were made when.

## Decision

### Amortizing products: same machine, per-product calibration

`AmortizingProductCalibration` carries every product-specific parameter
(rates, terms, amounts, entry hazards, roll matrix, prepayment SMM, recovery
rate and lag); the simulator is untouched apart from reading its parameters
from the loan's product. The post-maturity arrears rule of ADR-0002 applies
to all three amortizing products as-is. The FFIEC 120-day default threshold
also applies to all three — for mortgages this is a documented
simplification (real foreclosure timelines are far longer); the mortgage
roll matrix compensates with the highest cure and stay probabilities of any
product, approximating the loss-mitigation pipeline without new states.

### Revolving model: simplified, explicit, honestly bounded

Cards get their own simulator (`revolving.py`) sharing the bucket state
machine, transition validation, and recovery flow. The monthly model:

- **Limit by band** at account opening (no limit changes over the account's
  life).
- **Spend draw toward a band-specific target utilization**: each current
  month the borrower draws `max(target − balance, 0) × U(0.5, 1.5)`, capped
  at the remaining headroom. Drawn balance therefore never exceeds the
  limit; the carried balance can exceed it only through capitalized
  delinquent interest, bounded by the charge-off clock (≤ 5 months of
  interest, ~12% worst case on the highest APR) — that bound is pinned by a
  test.
- **Three payment behaviors**, drawn per month: miss the minimum (hazard by
  band), pay the statement in full (transactor; grace period, zero interest
  that month), or revolve paying exactly the minimum — **interest plus 1% of
  the statement balance with a $30 floor**, the formula large issuers most
  commonly use (sources in docs/calibration-sources.md).
- **Revolving delinquency** reuses the cure/stay/roll-deeper machinery on
  missed minimums; the account is suspended (no draws) while delinquent.
  **Charge-off at 6 missed minimums — 180 days past due — per the FFIEC
  open-end rule**, with the months between 90 and 180 days staying in the
  90+ bucket. Charge-off writes off the full balance and feeds the same
  lagged-recovery flow as loans.
- **No maturity**: an account that never charges off emits a row every month
  through the as-of cutoff. There is no PAID_OFF state for cards.

Knowingly simplified away (documented, not hidden): no grace-period
mechanics beyond the transactor zero-interest month (no trailing interest),
no partial payments between minimum and full, no credit-limit increases, no
voluntary account closure or attrition, no balance-transfer or fee income,
interest charged on the carried balance only (not on the current month's
draws). Each cut keeps the model auditable; none change the delinquency
dynamics downstream phases consume.

### Schema: one table per entity, nullable product-specific columns

`loans` and `monthly_performance` stay single tables with a `product_type`
column threaded through both. Card-only fields (`credit_limit`,
`utilization_rate`, `draw_amount`) are NULL/zero on amortizing rows; amortizing
fields (`principal_amount`, `term_months`, `monthly_payment`) are NULL on
cards. The `Loan` constructor rejects any other combination, so nullability
is a contract, not an accident. A new `interest_charged` column separates
accrual from collection; every row of every product satisfies one balance
identity:

```
ending = beginning + draw + interest_charged
         − interest_paid − principal_paid − writeoff
```

### Book mix: configurable weights on the calibration

`Calibration.product_mix` draws each account's product (default: cards 0.55,
personal 0.20, auto 0.17, mortgage 0.08 by count — card-heavy by count,
mortgage-heavy by balance, matching the NY Fed household-debt composition
qualitatively; citations in docs/calibration-sources.md). Overriding the mix
is a one-field `dataclasses.replace`, which is also how the tests force
single-product books.

## Alternatives considered

- **Per-product tables (`loans` + `card_accounts`, split performance).**
  Cleaner nullability story, but every downstream consumer (staging models,
  risk marts, ECL) would need a UNION or two code paths per layer, and the
  event-sourced loan-state stream in Phase 2 wants one spine. The cost lands
  once in the generator (nullable columns + constructor validation) instead
  of in every consumer. Lost on downstream cost.
- **Subclassing the loan simulator for cards.** The lifecycle differences
  (no schedule, no maturity, draws, minimums) would override nearly every
  method; inheritance would couple two genuinely different processes to
  share a `run()` loop. A separate simulator sharing the state machine and
  the row type is smaller and more honest. Lost on coupling.
- **A productized "revolving as amortizing" hack** (treat each month's
  balance as a 1-month bullet loan). Would have reused more code but made
  utilization, minimum payments, and charge-off timing artifacts of the
  encoding — exactly the dynamics the risk layer needs to be real. Lost on
  statistical shape.
- **Amending ADR-0002 in place.** Rejected for the record-keeping reason
  above; ADR-0002 gets a status pointer to this ADR instead.
- **Separate per-product RNG streams (spawned seeds).** Would decouple the
  products' byte-streams (a calibration change to one product would not
  shift another product's draws), at the cost of a more complex seeding
  story. Not needed at this scale; reproducibility is pinned at the
  whole-book level. Revisit together with the parallel-generation note in
  ADR-0002.

## Consequences

- Phase 2 dbt models read one `loans` table and one `monthly_performance`
  stream with `product_type` as a first-class dimension; card-specific
  columns arrive NULL for other products by contract.
- The universal balance identity gives balance-reconciliation tests a single
  expression valid for every product; the suite pins it per product
  (principal conservation for amortizing; draw/limit and identity rules for
  revolving) plus aggregate shape (default and charge-off rates by band,
  utilization gradient).
- Because one RNG stream drives the whole book in a fixed order, *any*
  calibration change to *any* product changes the byte-stream of the whole
  book (same-seed reproducibility still holds; cross-version byte stability
  was already surrendered in ADR-0002).
- Mortgage populations make full-lifecycle testing expensive (360-month
  terms); the test populations cap sizes and the two best score bands
  realize too few defaults for strict ordering assertions — the aggregate
  tests order the three worst bands strictly and bound the best two instead.
- The young default book (cohorts at most 36 months on book) cannot
  reproduce point-in-time delinquency anchors for slow-seasoning products;
  mortgage and card PIT delinquency run under their anchors, documented in
  docs/calibration-sources.md rather than tuned away.
