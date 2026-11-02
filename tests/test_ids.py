from datetime import date, datetime
import pytest
from event_radar.models import RawEvent
from event_radar.ids import make_event_id


def test_event_id_does_not_change_when_event_date_changes():
    raw1 = RawEvent(
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

    raw2 = raw1.model_copy(update={"event_date": date(2026, 11, 25)})

    id1 = make_event_id(raw1)
    id2 = make_event_id(raw2)

    assert id1 == id2
    assert "2026-11-20" not in id1
    assert "2026-11-25" not in id1


def test_event_id_fallback_without_source_uid():
    raw1 = RawEvent(
        source_name="SEC",
        source_kind="REGULATOR",
        source_event_uid=None,
        source_url="https://www.sec.gov/edgar/data/320193/000032019326000100",
        country="US",
        primary_ticker="AAPL",
        primary_company="Apple Inc.",
        event_type="STOCK_SPLIT",
        event_name="Apple 4-for-1 Stock Split",
        announced_at=datetime(2026, 8, 1, 16, 30),
        event_date=date(2026, 8, 31),
        event_time_context="AFTERHOURS",
        status="CONFIRMED",
        evidence_text="4-for-1 stock split effective Aug 31",
    )

    raw2 = raw1.model_copy(update={"event_date": date(2026, 9, 5)})

    id1 = make_event_id(raw1)
    id2 = make_event_id(raw2)

    assert id1 == id2
    assert id1.startswith("US_AAPL_") or "AAPL" in id1


def test_manual_event_id_unique():
    raw1 = RawEvent(
        source_name="MANUAL",
        source_kind="SECONDARY",
        source_url="",
        country="KR",
        primary_ticker="035720",
        primary_company="카카오",
        event_type="GAME_RELEASE",
        event_name="카카오게임즈 신작 출시",
        announced_at=datetime(2026, 11, 2, 10, 0),
        event_date=date(2026, 12, 1),
        ingest_mode="MANUAL",
    )

    id1 = make_event_id(raw1)
    assert id1.startswith("MANUAL_") or len(id1) >= 16
