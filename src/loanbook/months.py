"""First-of-month date arithmetic for cohort and reporting calendars."""

from datetime import date, datetime

MONTHS_PER_YEAR = 12
MONTH_FORMAT = "%Y-%m"


def add_months(month: date, count: int) -> date:
    """Return the first-of-month date `count` months after `month`."""
    total_months = month.year * MONTHS_PER_YEAR + (month.month - 1) + count
    return date(total_months // MONTHS_PER_YEAR, total_months % MONTHS_PER_YEAR + 1, 1)


def parse_month(month_text: str) -> date:
    """Parse 'YYYY-MM' into a first-of-month date."""
    return datetime.strptime(month_text, MONTH_FORMAT).date()
