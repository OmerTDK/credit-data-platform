"""Delinquency state machine: explicit legal transitions, everything else rejected.

Bucket semantics follow the New York Fed Consumer Credit Panel delinquency
statuses (30/60/90+ days past due). Default at four missed monthly payments
mirrors the FFIEC Uniform Retail Credit Classification policy: closed-end
retail loans are charged off at 120 days past due. Sources in
docs/calibration-sources.md.
"""

from enum import StrEnum


class DelinquencyBucket(StrEnum):
    CURRENT = "current"
    DPD_30 = "dpd_30"
    DPD_60 = "dpd_60"
    DPD_90_PLUS = "dpd_90_plus"
    DEFAULT = "default"


class LoanStatus(StrEnum):
    ACTIVE = "active"
    PAID_OFF = "paid_off"
    DEFAULTED = "defaulted"
    RECOVERY_COMPLETE = "recovery_complete"


class IllegalTransitionError(Exception):
    """Raised when a delinquency bucket transition is not in the legal set."""


MISSED_PAYMENTS_FOR_DEFAULT = 4

_BUCKET_BY_MISSED_PAYMENTS = (
    DelinquencyBucket.CURRENT,
    DelinquencyBucket.DPD_30,
    DelinquencyBucket.DPD_60,
    DelinquencyBucket.DPD_90_PLUS,
    DelinquencyBucket.DEFAULT,
)

LEGAL_BUCKET_TRANSITIONS: dict[DelinquencyBucket, frozenset[DelinquencyBucket]] = {
    DelinquencyBucket.CURRENT: frozenset({DelinquencyBucket.CURRENT, DelinquencyBucket.DPD_30}),
    DelinquencyBucket.DPD_30: frozenset(
        {DelinquencyBucket.CURRENT, DelinquencyBucket.DPD_30, DelinquencyBucket.DPD_60}
    ),
    DelinquencyBucket.DPD_60: frozenset(
        {DelinquencyBucket.CURRENT, DelinquencyBucket.DPD_60, DelinquencyBucket.DPD_90_PLUS}
    ),
    DelinquencyBucket.DPD_90_PLUS: frozenset(
        {DelinquencyBucket.CURRENT, DelinquencyBucket.DPD_90_PLUS, DelinquencyBucket.DEFAULT}
    ),
    DelinquencyBucket.DEFAULT: frozenset(),
}

TERMINAL_STATUSES = frozenset({LoanStatus.PAID_OFF, LoanStatus.RECOVERY_COMPLETE})


def validate_bucket_transition(
    from_bucket: DelinquencyBucket, to_bucket: DelinquencyBucket
) -> None:
    """Raise IllegalTransitionError unless from_bucket -> to_bucket is legal.

    Legal moves are: stay in place, roll exactly one bucket deeper, or cure
    back to current by paying all arrears. Default is absorbing.
    """
    if to_bucket not in LEGAL_BUCKET_TRANSITIONS[from_bucket]:
        raise IllegalTransitionError(
            f"Illegal delinquency transition: {from_bucket.value} -> {to_bucket.value}. "
            f"Legal targets: {sorted(LEGAL_BUCKET_TRANSITIONS[from_bucket])}"
        )


def bucket_for_missed_payments(missed_payments: int) -> DelinquencyBucket:
    """Map a count of consecutive missed monthly payments to its bucket."""
    if missed_payments < 0 or missed_payments > MISSED_PAYMENTS_FOR_DEFAULT:
        raise ValueError(
            f"missed_payments must be between 0 and {MISSED_PAYMENTS_FOR_DEFAULT}, "
            f"got {missed_payments}"
        )
    return _BUCKET_BY_MISSED_PAYMENTS[missed_payments]
