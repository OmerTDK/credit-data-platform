"""Delinquency state machine: explicit legal transitions, everything else rejected.

Bucket semantics follow the New York Fed Consumer Credit Panel delinquency
statuses (30/60/90+ days past due). Default thresholds mirror the FFIEC
Uniform Retail Credit Classification policy: closed-end retail loans are
charged off at 120 days past due (4 missed monthly payments) and open-end
retail credit at 180 days past due (6 missed minimum payments, the months
between 90 and 180 days staying in the 90+ bucket). Sources in
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
MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING = 6

_BUCKET_BY_MISSED_PAYMENTS = (
    DelinquencyBucket.CURRENT,
    DelinquencyBucket.DPD_30,
    DelinquencyBucket.DPD_60,
    DelinquencyBucket.DPD_90_PLUS,
    DelinquencyBucket.DEFAULT,
)
_DEEPEST_PRE_DEFAULT_INDEX = len(_BUCKET_BY_MISSED_PAYMENTS) - 2

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
    DelinquencyBucket.DEFAULT: frozenset({DelinquencyBucket.DEFAULT}),
}

TERMINAL_STATUSES = frozenset({LoanStatus.PAID_OFF, LoanStatus.RECOVERY_COMPLETE})


def validate_bucket_transition(
    from_bucket: DelinquencyBucket, to_bucket: DelinquencyBucket
) -> None:
    """Raise IllegalTransitionError unless from_bucket -> to_bucket is legal.

    Legal moves are: stay in place, roll exactly one bucket deeper, or cure
    back to current by paying all arrears. Default is absorbing: it only
    transitions to itself (recovery-flow rows keep the default bucket).
    """
    if to_bucket not in LEGAL_BUCKET_TRANSITIONS[from_bucket]:
        raise IllegalTransitionError(
            f"Illegal delinquency transition: {from_bucket.value} -> {to_bucket.value}. "
            f"Legal targets: {sorted(LEGAL_BUCKET_TRANSITIONS[from_bucket])}"
        )


def next_deeper_bucket(bucket: DelinquencyBucket) -> DelinquencyBucket:
    """Return the bucket one delinquency stage deeper than `bucket`.

    Default is absorbing, so it has no deeper bucket and raises ValueError.
    """
    if bucket == DelinquencyBucket.DEFAULT:
        raise ValueError("default is absorbing: there is no bucket deeper than default")
    return _BUCKET_BY_MISSED_PAYMENTS[_BUCKET_BY_MISSED_PAYMENTS.index(bucket) + 1]


def bucket_for_missed_payments(
    missed_payments: int,
    missed_payments_for_default: int = MISSED_PAYMENTS_FOR_DEFAULT,
) -> DelinquencyBucket:
    """Map a count of consecutive missed monthly payments to its bucket.

    The default threshold is product-dependent: 4 missed payments for
    closed-end loans (120 days, FFIEC) and 6 for revolving credit (180 days,
    FFIEC). Counts between the 90+ stage and the threshold stay in the 90+
    bucket — days past due keep accruing but there is no deeper pre-default
    stage to move to.
    """
    if missed_payments < 0 or missed_payments > missed_payments_for_default:
        raise ValueError(
            f"missed_payments must be between 0 and {missed_payments_for_default}, "
            f"got {missed_payments}"
        )
    if missed_payments == missed_payments_for_default:
        return DelinquencyBucket.DEFAULT
    return _BUCKET_BY_MISSED_PAYMENTS[min(missed_payments, _DEEPEST_PRE_DEFAULT_INDEX)]
