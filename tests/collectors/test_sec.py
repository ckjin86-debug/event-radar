from datetime import datetime, date
from pathlib import Path
import pytest
from event_radar.collectors.sec import SecCollector


def test_sec_collector_parses_fixtures():
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sec" / "sample_submissions.json"
    collector = SecCollector(fixture_path=fixture_path)

    events = collector.collect(since=datetime(2026, 10, 1))
    assert len(events) == 2

    # 1. Earnings 8-K
    evt1 = [e for e in events if e.event_type == "EARNINGS"][0]
    assert evt1.primary_ticker == "AAPL"
    assert evt1.country == "US"
    assert evt1.source_event_uid == "0000320193-26-000101"
    assert evt1.event_time_context == "AFTERHOURS"

    # 2. Stock Split 8-K
    evt2 = [e for e in events if e.event_type == "STOCK_SPLIT"][0]
    assert evt2.primary_ticker == "AAPL"
    assert evt2.event_date == date(2026, 11, 20)
    assert evt2.source_event_uid == "0000320193-26-000102"


def test_sec_collector_user_agent_format():
    collector = SecCollector()
    ua = collector.session.headers.get("User-Agent", "")
    assert "@" in ua  # SEC strictly requires contact email in User-Agent
    assert len(ua.split()) >= 2


def test_sec_collector_graceful_on_error(monkeypatch):
    collector = SecCollector()

    def mock_get(*args, **kwargs):
        raise ConnectionError("SEC EDGAR down")

    monkeypatch.setattr("requests.Session.get", mock_get)
    events = collector.collect(since=datetime(2026, 10, 1))
    assert events == []
