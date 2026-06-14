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
            and to_delinquency_bucket not in ('dpd_30', 'default')
        )
        or (
            from_delinquency_bucket = 'dpd_30'
            and to_delinquency_bucket not in ('current', 'dpd_60', 'default')
        )
        or (
            from_delinquency_bucket = 'dpd_60'
            and to_delinquency_bucket not in ('current', 'dpd_90_plus', 'default')
        )
        or (
            from_delinquency_bucket = 'dpd_90_plus'
            and to_delinquency_bucket not in ('current', 'default')
        )
        or from_delinquency_bucket = 'default'
    )
