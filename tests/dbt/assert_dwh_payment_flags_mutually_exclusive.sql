-- Verify that is_paid_in_full and is_missed_payment are mutually exclusive for
-- rows with a scheduled payment amount greater than zero.
--
-- When scheduled_payment_amount = 0 (terminal rows in defaulted/recovery_complete status),
-- both `actual_payment_amount >= scheduled_payment_amount` (0 >= 0 = TRUE) and
-- `actual_payment_amount = 0` (TRUE) evaluate simultaneously. This is a degenerate
-- numeric case, not a real payment conflict; the guard `scheduled_payment_amount > 0`
-- excludes these rows.
--
-- Any row with scheduled_payment_amount > 0 where both flags are TRUE indicates
-- a logic bug in the payment flag definitions.
select
    loan_id,
    months_on_book,
    loan_status,
    scheduled_payment_amount,
    actual_payment_amount,
    is_paid_in_full,
    is_missed_payment
from {{ ref('fct_payment') }}
where
    is_paid_in_full
    and is_missed_payment
    and scheduled_payment_amount > 0
