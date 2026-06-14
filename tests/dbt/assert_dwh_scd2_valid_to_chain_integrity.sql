-- Verify SCD2 _valid_to chain integrity in dim_borrower:
-- for every non-current version row, _valid_to must equal the immediately
-- following version's _valid_from (LEAD offset 1, not 2 or more).
--
-- A wrong LEAD offset (e.g. LEAD(_valid_from, 2)) would create a 1-month gap
-- in the SCD2 timeline for borrowers with multiple versions. All other SCD2
-- tests (_valid_from monotonic, one _is_current row per borrower) remain green
-- under that mutation — only this test catches it.
select
    borrower_id,
    version_number,
    _valid_to,
    lead(_valid_from) over (
        partition by borrower_id order by version_number
    ) as next_valid_from
from {{ ref('dim_borrower') }}
qualify
    next_valid_from is not null
    and _valid_to != next_valid_from
