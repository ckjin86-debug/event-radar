from datetime import datetime, date
from pathlib import Path
import pytest
from event_radar.collectors.dart import DartCollector


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


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


def test_dart_collector_excludes_generic_rights_issue(monkeypatch):
    collector = DartCollector(api_key="TEST_KEY")

    list_payload = {
        "status": "000",
        "list": [
            {
                "corp_code": "00126380",
                "corp_name": "테스트기업",
                "stock_code": "123456",
                "report_nm": "주요사항보고서(유상증자결정)",
                "rcept_no": "20261103000001",
                "rcept_dt": "20261103",
            }
        ],
    }
    detail_payload = {
        "status": "000",
        "list": [
            {
                "rcept_no": "20261103000001",
                "corp_code": "00126380",
                "fdpp_fclt": "0",
                "fdpp_op": "10,000,000,000",
            }
        ],
    }

    def mock_get(url, *args, **kwargs):
        if "piicDecsn.json" in url:
            return FakeResponse(detail_payload)
        return FakeResponse(list_payload)

    monkeypatch.setattr(collector.session, "get", mock_get)

    events = collector.collect(since=datetime(2026, 11, 1))

    assert events == []


def test_dart_collector_keeps_facility_financing_rights_issue(monkeypatch):
    collector = DartCollector(api_key="TEST_KEY")

    list_payload = {
        "status": "000",
        "list": [
            {
                "corp_code": "00126380",
                "corp_name": "테스트기업",
                "stock_code": "123456",
                "report_nm": "주요사항보고서(유상증자결정)",
                "rcept_no": "20261103000002",
                "rcept_dt": "20261103",
            }
        ],
    }
    detail_payload = {
        "status": "000",
        "list": [
            {
                "rcept_no": "20261103000002",
                "corp_code": "00126380",
                "fdpp_fclt": "5,000,000,000",
                "fdpp_op": "0",
            }
        ],
    }

    def mock_get(url, *args, **kwargs):
        if "piicDecsn.json" in url:
            return FakeResponse(detail_payload)
        return FakeResponse(list_payload)

    monkeypatch.setattr(collector.session, "get", mock_get)

    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 1
    assert events[0].event_type == "CAPEX_FINANCING"
    assert "시설자금" in events[0].evidence_text
    assert "5,000,000,000" in events[0].evidence_text


def test_dart_collector_graceful_on_api_error(monkeypatch):
    collector = DartCollector(api_key="INVALID_KEY")

    # Force network failure
    def mock_get(*args, **kwargs):
        raise ConnectionError("DART API unreachable")

    monkeypatch.setattr("requests.Session.get", mock_get)

    # Should not raise exception, return empty list gracefully and log failure
    events = collector.collect(since=datetime(2026, 11, 1))
    assert events == []
