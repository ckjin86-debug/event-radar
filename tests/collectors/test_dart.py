from datetime import datetime, date
from pathlib import Path
import pytest
from event_radar.collectors.dart import DartCollector


def test_dart_collector_parses_fixtures():
    fixture_path = Path(__file__).parent.parent / "fixtures" / "dart" / "sample_disclosures.json"
    collector = DartCollector(fixture_path=fixture_path)

    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 3

    # 1. 무상증자
    evt1 = [e for e in events if e.primary_ticker == "005930"][0]
    assert evt1.event_type == "BONUS_ISSUE"
    assert evt1.source_event_uid == "20261102000543"
    assert evt1.country == "KR"
    assert evt1.event_date == date(2026, 11, 20)
    assert evt1.status == "CONFIRMED"

    # 2. CB 전환상장
    evt2 = [e for e in events if e.primary_ticker == "000660"][0]
    assert evt2.event_type == "CONVERTIBLE_LISTING"
    assert evt2.event_date == date(2026, 11, 18)

    # 3. 주식분할
    evt3 = [e for e in events if e.primary_ticker == "259960"][0]
    assert evt3.event_type == "STOCK_SPLIT"
    assert evt3.event_date == date(2026, 12, 5)


def test_dart_collector_graceful_on_api_error(monkeypatch):
    collector = DartCollector(api_key="INVALID_KEY")

    # Force network failure
    def mock_get(*args, **kwargs):
        raise ConnectionError("DART API unreachable")

    monkeypatch.setattr("requests.Session.get", mock_get)

    # Should not raise exception, return empty list gracefully and log failure
    events = collector.collect(since=datetime(2026, 11, 1))
    assert events == []
