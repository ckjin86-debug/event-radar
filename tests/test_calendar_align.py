from datetime import date
import pytest
import pandas as pd
from event_radar.backtest.align import resolve_event_session
from event_radar.prices.calendar import get_trading_calendar


def test_weekend_date_only_moves_to_next_trading_day():
    # 2026-11-07 is Saturday, 2026-11-08 is Sunday, 2026-11-09 is Monday
    trading_days = [
        date(2026, 11, 5),
        date(2026, 11, 6),  # Friday
        date(2026, 11, 9),  # Monday
        date(2026, 11, 10),
    ]

    # Saturday DATE_ONLY
    session, conf = resolve_event_session(date(2026, 11, 7), "DATE_ONLY", trading_days)
    assert session == date(2026, 11, 9)
    assert conf == "LOW"

    # Sunday DATE_ONLY
    session, conf = resolve_event_session(date(2026, 11, 8), "DATE_ONLY", trading_days)
    assert session == date(2026, 11, 9)
    assert conf == "LOW"


def test_afterhours_moves_to_next_trading_day():
    # Friday after-hours should react on Monday
    trading_days = [
        date(2026, 11, 6),  # Friday
        date(2026, 11, 9),  # Monday
    ]

    session, conf = resolve_event_session(date(2026, 11, 6), "AFTERHOURS", trading_days)
    assert session == date(2026, 11, 9)
    assert conf == "HIGH"


def test_premarket_on_trading_day_stays_same_day():
    trading_days = [
        date(2026, 11, 6),  # Friday
        date(2026, 11, 9),  # Monday
    ]

    session, conf = resolve_event_session(date(2026, 11, 6), "PREMARKET", trading_days)
    assert session == date(2026, 11, 6)
    assert conf == "HIGH"


def test_intraday_on_trading_day_stays_same_day():
    trading_days = [
        date(2026, 11, 6),  # Friday
        date(2026, 11, 9),  # Monday
    ]

    session, conf = resolve_event_session(date(2026, 11, 6), "INTRADAY", trading_days)
    assert session == date(2026, 11, 6)
    assert conf == "HIGH"


def test_trading_calendar_filters_weekends():
    days = get_trading_calendar(country="KR", start=date(2026, 11, 1), end=date(2026, 11, 15))
    # No Saturdays (weekday == 5) or Sundays (weekday == 6)
    for d in days:
        assert d.weekday() < 5
