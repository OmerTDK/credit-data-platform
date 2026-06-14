-- Verify two invariants for fct_loan_lifecycle milestone columns.
--
-- Invariant 1 (set-membership): a later delinquency stage cannot appear without
-- all earlier stages being present. A loan entering dpd_60 must have first entered
-- dpd_30; a loan entering dpd_90_plus must have first entered dpd_60; a defaulted
-- loan must have first entered dpd_90_plus. This is enforced by the state machine
-- (LEGAL_BUCKET_TRANSITIONS in state_machine.py) and must also hold in the lifecycle
-- milestone facts derived from the performance table.
--
-- Invariant 2 (ordering): when two stages are both present, the earlier stage must
-- have a lower report_month than the later one. This was the original test, but it
-- is vacuous when using the set-inclusion WHERE clauses (first_dpd30 <= first_dpd60
-- by construction); keeping it here as a documentation check alongside invariant 1.
select
    loan_id,
    first_dpd30_month,
    first_dpd60_month,
    first_dpd90_month,
    default_month
from {{ ref('fct_loan_lifecycle') }}
where
    -- Invariant 1: set-membership gaps are impossible per the state machine.
    (first_dpd60_month is not null and first_dpd30_month is null)
    or (first_dpd90_month is not null and first_dpd60_month is null)
    or (default_month is not null and first_dpd90_month is null)
    -- Invariant 2: when both milestones are present the earlier one must precede.
    or (
        first_dpd60_month is not null
        and first_dpd30_month is not null
        and first_dpd60_month < first_dpd30_month
    )
    or (
        first_dpd90_month is not null
        and first_dpd60_month is not null
        and first_dpd90_month < first_dpd60_month
    )
    or (
        default_month is not null
        and first_dpd90_month is not null
        and default_month < first_dpd90_month
    )
