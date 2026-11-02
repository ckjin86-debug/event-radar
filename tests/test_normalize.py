from datetime import date, datetime
import pytest
from event_radar.models import RawEvent, Event
from event_radar.normalize import normalize_event


def test_normalize_raw_event_to_canonical_event():
    raw = RawEvent(
        source_name="DART",
        source_kind="REGULATOR",
        source_event_uid="20261102000123",
        source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261102000123",
        country="KR",
        primary_ticker="005930",
        primary_company="삼성전자",
        event_type="BONUS_ISSUE",
        event_name="삼성전자 무상증자 신주배정",
        announced_at=datetime(2026, 11, 2, 9, 30),
        event_date=date(2026, 11, 20),
        event_time_context="DATE_ONLY",
        status="CONFIRMED",
        evidence_text="1주당 신주 0.5주 배정",
    )

    now = datetime(2026, 11, 2, 12, 0, 0)
    event = normalize_event(raw, now=now)

    assert isinstance(event, Event)
    assert event.event_id != ""
    assert event.primary_ticker == "005930"
    assert event.event_date == date(2026, 11, 20)
    assert event.first_seen_at == now
    assert event.last_seen_at == now
    assert event.needs_review is False
    assert event.ingest_mode == "AUTO"


def test_normalize_strips_ticker_and_uppercases():
    raw = RawEvent(
        source_name="SEC",
        source_kind="REGULATOR",
        source_url="https://sec.gov/filing",
        country="us",
        primary_ticker="  aapl  ",
        primary_company="Apple Inc.",
        event_type="earnings",
        event_name="Q4 Earnings",
        announced_at=datetime(2026, 10, 1),
        event_date=date(2026, 10, 30),
    )

    event = normalize_event(raw)
    assert event.country == "US"
    assert event.primary_ticker == "AAPL"
    assert event.event_type == "EARNINGS"
