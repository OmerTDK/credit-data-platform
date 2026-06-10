"""Tests for the delinquency state machine: legal transitions only, terminal states final."""

import pytest

from loanbook.state_machine import (
    LEGAL_BUCKET_TRANSITIONS,
    MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING,
    MISSED_PAYMENTS_FOR_DEFAULT,
    TERMINAL_STATUSES,
    DelinquencyBucket,
    IllegalTransitionError,
    LoanStatus,
    bucket_for_missed_payments,
    next_deeper_bucket,
    validate_bucket_transition,
)


class TestDelinquencyBucket:
    def test_buckets_are_exactly_the_five_industry_stages(self) -> None:
        assert {bucket.value for bucket in DelinquencyBucket} == {
            "current",
            "dpd_30",
            "dpd_60",
            "dpd_90_plus",
            "default",
        }

    def test_bucket_values_are_strings(self) -> None:
        assert DelinquencyBucket.CURRENT == "current"
        assert DelinquencyBucket.DPD_90_PLUS == "dpd_90_plus"


class TestLegalTransitions:
    def test_transition_table_is_one_step_deeper_stay_or_cure(self) -> None:
        assert {
            DelinquencyBucket.CURRENT: frozenset(
                {DelinquencyBucket.CURRENT, DelinquencyBucket.DPD_30}
            ),
            DelinquencyBucket.DPD_30: frozenset(
                {
                    DelinquencyBucket.CURRENT,
                    DelinquencyBucket.DPD_30,
                    DelinquencyBucket.DPD_60,
                }
            ),
            DelinquencyBucket.DPD_60: frozenset(
                {
                    DelinquencyBucket.CURRENT,
                    DelinquencyBucket.DPD_60,
                    DelinquencyBucket.DPD_90_PLUS,
                }
            ),
            DelinquencyBucket.DPD_90_PLUS: frozenset(
                {
                    DelinquencyBucket.CURRENT,
                    DelinquencyBucket.DPD_90_PLUS,
                    DelinquencyBucket.DEFAULT,
                }
            ),
            DelinquencyBucket.DEFAULT: frozenset({DelinquencyBucket.DEFAULT}),
        } == LEGAL_BUCKET_TRANSITIONS

    @pytest.mark.parametrize(
        ("from_bucket", "to_bucket"),
        [
            (DelinquencyBucket.CURRENT, DelinquencyBucket.DPD_60),
            (DelinquencyBucket.CURRENT, DelinquencyBucket.DEFAULT),
            (DelinquencyBucket.DPD_30, DelinquencyBucket.DPD_90_PLUS),
            (DelinquencyBucket.DPD_60, DelinquencyBucket.DPD_30),
            (DelinquencyBucket.DPD_90_PLUS, DelinquencyBucket.DPD_60),
            (DelinquencyBucket.DEFAULT, DelinquencyBucket.CURRENT),
            (DelinquencyBucket.DEFAULT, DelinquencyBucket.DPD_90_PLUS),
        ],
    )
    def test_illegal_transitions_are_rejected(
        self, from_bucket: DelinquencyBucket, to_bucket: DelinquencyBucket
    ) -> None:
        with pytest.raises(IllegalTransitionError, match=f"{from_bucket.value}.*{to_bucket.value}"):
            validate_bucket_transition(from_bucket, to_bucket)

    def test_legal_transitions_pass_validation(self) -> None:
        for from_bucket, allowed in LEGAL_BUCKET_TRANSITIONS.items():
            for to_bucket in allowed:
                validate_bucket_transition(from_bucket, to_bucket)

    def test_default_bucket_is_absorbing(self) -> None:
        assert LEGAL_BUCKET_TRANSITIONS[DelinquencyBucket.DEFAULT] == frozenset(
            {DelinquencyBucket.DEFAULT}
        )


class TestBucketForMissedPayments:
    @pytest.mark.parametrize(
        ("missed_payments", "expected_bucket"),
        [
            (0, DelinquencyBucket.CURRENT),
            (1, DelinquencyBucket.DPD_30),
            (2, DelinquencyBucket.DPD_60),
            (3, DelinquencyBucket.DPD_90_PLUS),
            (4, DelinquencyBucket.DEFAULT),
        ],
    )
    def test_maps_missed_payment_count_to_bucket(
        self, missed_payments: int, expected_bucket: DelinquencyBucket
    ) -> None:
        assert bucket_for_missed_payments(missed_payments) == expected_bucket

    def test_default_threshold_is_ffiec_120_days(self) -> None:
        assert MISSED_PAYMENTS_FOR_DEFAULT == 4

    def test_counts_beyond_default_threshold_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="missed_payments"):
            bucket_for_missed_payments(5)

    def test_negative_count_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="missed_payments"):
            bucket_for_missed_payments(-1)


class TestRevolvingChargeOffThreshold:
    """Open-end retail credit charges off at 180 days past due (FFIEC policy),
    so a card defaults at 6 missed minimum payments instead of 4; the months
    between 90 and 180 days stay in the dpd_90_plus bucket."""

    def test_revolving_charge_off_threshold_is_ffiec_180_days(self) -> None:
        assert MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING == 6

    @pytest.mark.parametrize(
        ("missed_payments", "expected_bucket"),
        [
            (0, DelinquencyBucket.CURRENT),
            (1, DelinquencyBucket.DPD_30),
            (2, DelinquencyBucket.DPD_60),
            (3, DelinquencyBucket.DPD_90_PLUS),
            (4, DelinquencyBucket.DPD_90_PLUS),
            (5, DelinquencyBucket.DPD_90_PLUS),
            (6, DelinquencyBucket.DEFAULT),
        ],
    )
    def test_maps_missed_minimums_to_bucket_under_the_revolving_threshold(
        self, missed_payments: int, expected_bucket: DelinquencyBucket
    ) -> None:
        bucket = bucket_for_missed_payments(
            missed_payments, missed_payments_for_default=MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING
        )
        assert bucket == expected_bucket

    def test_counts_beyond_the_revolving_threshold_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="missed_payments"):
            bucket_for_missed_payments(
                7, missed_payments_for_default=MISSED_PAYMENTS_FOR_CHARGE_OFF_REVOLVING
            )

    def test_aging_within_90_plus_is_a_legal_stay_transition(self) -> None:
        validate_bucket_transition(DelinquencyBucket.DPD_90_PLUS, DelinquencyBucket.DPD_90_PLUS)


class TestNextDeeperBucket:
    @pytest.mark.parametrize(
        ("bucket", "expected_deeper"),
        [
            (DelinquencyBucket.CURRENT, DelinquencyBucket.DPD_30),
            (DelinquencyBucket.DPD_30, DelinquencyBucket.DPD_60),
            (DelinquencyBucket.DPD_60, DelinquencyBucket.DPD_90_PLUS),
            (DelinquencyBucket.DPD_90_PLUS, DelinquencyBucket.DEFAULT),
        ],
    )
    def test_steps_exactly_one_bucket_deeper(
        self, bucket: DelinquencyBucket, expected_deeper: DelinquencyBucket
    ) -> None:
        assert next_deeper_bucket(bucket) == expected_deeper

    def test_stepping_deeper_is_always_a_legal_transition(self) -> None:
        for bucket in DelinquencyBucket:
            if bucket == DelinquencyBucket.DEFAULT:
                continue
            validate_bucket_transition(bucket, next_deeper_bucket(bucket))

    def test_default_has_no_deeper_bucket(self) -> None:
        with pytest.raises(ValueError, match="default"):
            next_deeper_bucket(DelinquencyBucket.DEFAULT)


class TestLoanStatus:
    def test_statuses_cover_the_loan_lifecycle(self) -> None:
        assert {status.value for status in LoanStatus} == {
            "active",
            "paid_off",
            "defaulted",
            "recovery_complete",
        }

    def test_terminal_statuses_are_paid_off_and_recovery_complete(self) -> None:
        assert frozenset({LoanStatus.PAID_OFF, LoanStatus.RECOVERY_COMPLETE}) == TERMINAL_STATUSES

    def test_defaulted_is_not_terminal_until_recovery_completes(self) -> None:
        assert LoanStatus.DEFAULTED not in TERMINAL_STATUSES
