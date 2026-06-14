-- Verify that all delinquency_transition events have legally allowed bucket transitions.
-- Legal transitions mirror LEGAL_BUCKET_TRANSITIONS in src/loanbook/state_machine.py exactly:
--   current   -> dpd_30            (one step deeper; self-transitions excluded from event stream)
--   dpd_30    -> current | dpd_60  (cure or one step deeper)
--   dpd_60    -> current | dpd_90_plus
--   dpd_90_plus -> current | default
--   default   -> (none; absorbing state, no further delinquency_transitions)
--
-- Allowing skip-to-default (e.g. current -> default, dpd_30 -> default, dpd_60 -> default)
-- would mask generator bugs. Only dpd_90_plus -> default is a legal one-step path to default.
select
    loan_id,
    months_on_book,
    from_delinquency_bucket,
    to_delinquency_bucket
from {{ ref('fct_loan_state_event') }}
where
    event_type = 'delinquency_transition'
    and (
        (
            from_delinquency_bucket = 'current'
            and to_delinquency_bucket not in ('dpd_30')
        )
        or (
            from_delinquency_bucket = 'dpd_30'
            and to_delinquency_bucket not in ('current', 'dpd_60')
        )
        or (
            from_delinquency_bucket = 'dpd_60'
            and to_delinquency_bucket not in ('current', 'dpd_90_plus')
        )
        or (
            from_delinquency_bucket = 'dpd_90_plus'
            and to_delinquency_bucket not in ('current', 'default')
        )
        or from_delinquency_bucket = 'default'
    )
