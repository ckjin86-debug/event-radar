"""Trading calendar and trading day helper functions."""

from __future__ import annotations
from datetime import date, timedelta


# Major fixed annual holidays (month, day)
KR_FIXED_HOLIDAYS = {
    (1, 1),   # New Year's Day
    (3, 1),   # Independence Movement Day
    (5, 5),   # Children's Day
    (6, 6),   # Memorial Day
    (8, 15),  # Liberation Day
    (10, 3),  # National Foundation Day
    (10, 9),  # Hangul Day
    (12, 25), # Christmas
}

US_FIXED_HOLIDAYS = {
    (1, 1),   # New Year's Day
    (6, 19),  # Juneteenth
    (7, 4),   # Independence Day
    (12, 25), # Christmas
}


def is_trading_day(d: date, country: str = "KR") -> bool:
    """Check if a date is a likely trading day (not a weekend and not a fixed holiday)."""
    # 5: Saturday, 6: Sunday
    if d.weekday() >= 5:
        return False
    holidays = US_FIXED_HOLIDAYS if country.upper() == "US" else KR_FIXED_HOLIDAYS
    if (d.month, d.day) in holidays:
        return False
    return True


def get_trading_calendar(country: str, start: date, end: date) -> list[date]:
    """Generate list of trading dates between start and end inclusive."""
    days: list[date] = []
    curr = start
    while curr <= end:
        if is_trading_day(curr, country):
            days.append(curr)
        curr += timedelta(days=1)
    return days
