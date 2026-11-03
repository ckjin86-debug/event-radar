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

    # 2. CB 전환청구로 실제 신주상장
    evt2 = [e for e in events if e.primary_ticker == "000660"][0]
    assert evt2.event_type == "CONVERTIBLE_LISTING"
    assert evt2.event_date == date(2026, 11, 18)

    # 3. 주식분할
    evt3 = [e for e in events if e.primary_ticker == "259960"][0]
    assert evt3.event_type == "STOCK_SPLIT"
    assert evt3.event_date == date(2026, 12, 5)


def test_dart_collector_excludes_generic_convertible_financing_disclosures(tmp_path):
    fixture = tmp_path / "convertibles.json"
    fixture.write_text(
        '''{
          "status": "000",
          "list": [
            {"corp_code":"00000001","corp_name":"A사","stock_code":"111111","report_nm":"전환사채권발행결정","rcept_no":"1","rcept_dt":"20261103","details":"운영자금 조달"},
            {"corp_code":"00000002","corp_name":"B사","stock_code":"222222","report_nm":"전환가액의조정","rcept_no":"2","rcept_dt":"20261103","details":"전환가액 조정"},
            {"corp_code":"00000003","corp_name":"C사","stock_code":"333333","report_nm":"자기전환사채만기전취득결정","rcept_no":"3","rcept_dt":"20261103","details":"만기 전 취득"},
            {"corp_code":"00000004","corp_name":"D사","stock_code":"444444","report_nm":"자기전환사채매도결정","rcept_no":"4","rcept_dt":"20261103","details":"매도 결정"},
            {"corp_code":"00000005","corp_name":"E사","stock_code":"555555","report_nm":"신주인수권부사채권발행결정","rcept_no":"5","rcept_dt":"20261103","details":"운영자금 조달"}
          ]
        }''',
        encoding="utf-8",
    )

    events = DartCollector(fixture_path=fixture).collect(since=datetime(2026, 11, 1))

    assert events == []


def test_dart_collector_keeps_explicit_convertible_new_share_listing(tmp_path):
    fixture = tmp_path / "convertible_listing.json"
    fixture.write_text(
        '''{
          "status": "000",
          "list": [
            {
              "corp_code":"00000001",
              "corp_name":"A사",
              "stock_code":"111111",
              "report_nm":"전환사채(CB)전환청구권행사(신주상장)",
              "rcept_no":"20261103000011",
              "rcept_dt":"20261103",
              "event_date":"2026-11-18",
              "details":"전환청구권 행사, 신주상장예정일: 2026-11-18"
            }
          ]
        }''',
        encoding="utf-8",
    )

    events = DartCollector(fixture_path=fixture).collect(since=datetime(2026, 11, 1))

    assert len(events) == 1
    assert events[0].event_type == "CONVERTIBLE_LISTING"
    assert events[0].event_date == date(2026, 11, 18)


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
