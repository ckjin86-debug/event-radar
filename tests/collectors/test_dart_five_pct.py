import json
from datetime import datetime, date
from pathlib import Path
import pytest
from event_radar.collectors.dart_five_pct import DartFivePctCollector


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


FIXTURE = Path(__file__).parent.parent / "fixtures" / "dart" / "sample_five_pct.json"


def test_five_pct_collector_parses_fixture_and_uses_majorstock_history():
    collector = DartFivePctCollector(fixture_path=FIXTURE)

    events = collector.collect(since=datetime(2026, 11, 1))

    # Only the two listed 대량보유 rows survive: the unlisted row has no
    # stock_code and the 임원 소유상황보고서 is not a 대량보유 report.
    assert {e.primary_ticker for e in events} == {"005930", "000660"}

    evt = [e for e in events if e.primary_ticker == "005930"][0]
    assert evt.source_name == "DART_5PCT"
    assert evt.source_kind == "REGULATOR"
    assert evt.event_type == "5PCT_OWNERSHIP"
    assert evt.source_event_uid == "20261105000111"
    assert evt.source_url == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261105000111"
    assert evt.country == "KR"
    assert evt.event_date == date(2026, 11, 5)
    assert evt.status == "CONFIRMED"
    assert evt.ingest_mode == "AUTO"

    # The latest majorstock row is the event: evidence and event name carry
    # the confirmed reporter / ratio facts from the official history.
    assert "국민연금공단" in evt.event_name
    assert "대표보고자 국민연금공단" in evt.evidence_text
    assert "보유비율 7.51%" in evt.evidence_text
    assert "증감 0.12%p" in evt.evidence_text
    assert "448,123,456" in evt.evidence_text

    # The ported rules analysis rides on the event: 국민연금공단 is a
    # passive investor, so the filing is classified NOISE with score 0.
    analysis = evt.raw_payload["five_pct_analysis"]
    assert analysis["alpha_score"] == 0
    assert analysis["investor_class"] == "패시브/연기금"
    assert analysis["investor_type"] == "PASSIVE"
    assert analysis["category"] == "NOISE"
    assert analysis["accumulation_count"] == 1
    assert analysis["purpose_current"] == "일반투자"
    assert analysis["purpose_prev"] == "일반투자"
    assert analysis["first_entry_dt"] == "2026-10-01"
    assert "elestock_detail" not in evt.raw_payload
    assert len(evt.raw_payload["history"]) == 2


def test_five_pct_collector_degrades_without_majorstock_or_elestock():
    collector = DartFivePctCollector(fixture_path=FIXTURE)

    events = collector.collect(since=datetime(2026, 11, 1))

    # SK하이닉스 has neither a majorstock nor an elestock fixture entry:
    # the filing is still collected from the list row alone (no invented
    # facts, no analysis payload).
    evt = [e for e in events if e.primary_ticker == "000660"][0]
    assert evt.evidence_text == "주식등의대량보유상황보고서(약식)"
    assert "대표보고자" not in evt.event_name
    assert "elestock_detail" not in evt.raw_payload
    assert "five_pct_analysis" not in evt.raw_payload


def test_five_pct_collector_uses_d001_discovery_and_paginates(monkeypatch):
    collector = DartFivePctCollector(api_key="TEST_KEY")

    page1 = {
        "status": "000",
        "page_no": 1,
        "page_count": 100,
        "total_count": 2,
        "total_page": 2,
        "list": [
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
                "report_nm": "주식등의대량보유상황보고서(일반)",
                "rcept_no": "20261105000111",
                "rcept_dt": "20261105",
            }
        ],
    }
    page2 = {
        "status": "000",
        "page_no": 2,
        "page_count": 100,
        "total_count": 2,
        "total_page": 2,
        "list": [
            {
                "corp_code": "00164779",
                "corp_name": "SK하이닉스",
                "stock_code": "000660",
                "report_nm": "주식등의대량보유상황보고서(약식)",
                "rcept_no": "20261104000999",
                "rcept_dt": "20261104",
            }
        ],
    }
    list_params = []
    majorstock_params = []

    def mock_get(url, *args, **kwargs):
        params = kwargs.get("params", {})
        if "majorstock" in url:
            majorstock_params.append(params)
            return FakeResponse({"status": "013", "list": []})
        if "elestock" in url:
            return FakeResponse({"status": "013", "list": []})
        list_params.append(params)
        return FakeResponse(page1 if params.get("page_no") == 1 else page2)

    monkeypatch.setattr(collector.session, "get", mock_get)

    events = collector.collect(since=datetime(2026, 11, 1))

    assert {e.primary_ticker for e in events} == {"005930", "000660"}
    assert len(list_params) == 2
    assert all(p.get("pblntf_ty") == "D" for p in list_params)
    assert all(p.get("pblntf_detail_ty") == "D001" for p in list_params)
    assert all(p.get("page_count") == 100 for p in list_params)
    # majorstock history was attempted once per discovered corp.
    assert {p.get("corp_code") for p in majorstock_params} == {"00126380", "00164779"}


def test_five_pct_collector_survives_history_and_elestock_failure(monkeypatch):
    collector = DartFivePctCollector(api_key="TEST_KEY")

    list_payload = {
        "status": "000",
        "total_page": 1,
        "list": [
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
                "report_nm": "주식등의대량보유상황보고서(일반)",
                "rcept_no": "20261105000111",
                "rcept_dt": "20261105",
            }
        ],
    }

    def mock_get(url, *args, **kwargs):
        if "majorstock" in url or "elestock" in url:
            raise ConnectionError("DART detail API unreachable")
        return FakeResponse(list_payload)

    monkeypatch.setattr(collector.session, "get", mock_get)

    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 1
    assert events[0].evidence_text == "주식등의대량보유상황보고서(일반)"


def test_five_pct_collector_graceful_on_list_api_error(monkeypatch):
    collector = DartFivePctCollector(api_key="INVALID_KEY")

    def mock_get(*args, **kwargs):
        raise ConnectionError("DART API unreachable")

    monkeypatch.setattr(collector.session, "get", mock_get)

    events = collector.collect(since=datetime(2026, 11, 1))
    assert events == []


def test_five_pct_collector_no_key_no_fixture_returns_empty(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    collector = DartFivePctCollector()

    events = collector.collect(since=datetime(2026, 11, 1))

    assert events == []


def _live_collector(monkeypatch, list_rows, majorstock_by_corp):
    collector = DartFivePctCollector(api_key="TEST_KEY")
    list_payload = {"status": "000", "total_page": 1, "list": list_rows}

    def mock_get(url, *args, **kwargs):
        if "majorstock" in url:
            corp_code = kwargs.get("params", {}).get("corp_code")
            rows = majorstock_by_corp.get(corp_code)
            if rows is None:
                return FakeResponse({"status": "013", "list": []})
            return FakeResponse({"status": "000", "list": rows})
        if "elestock" in url:
            return FakeResponse({"status": "013", "list": []})
        return FakeResponse(list_payload)

    monkeypatch.setattr(collector.session, "get", mock_get)
    return collector


def test_five_pct_collector_scores_majorstock_history(monkeypatch):
    list_rows = [
        {
            "corp_code": "00999999",
            "corp_name": "테스트전자",
            "stock_code": "123456",
            "report_nm": "주식등의대량보유상황보고서(일반)",
            "rcept_no": "20261102000001",
            "rcept_dt": "20261102",
            "flr_nm": "얼라인파트너스자산운용",
        }
    ]
    major_rows = [
        {
            "rcept_no": "20260901000001", "rcept_dt": "20260901",
            "corp_code": "00999999", "corp_name": "테스트전자",
            "repror": "얼라인파트너스자산운용",
            "stkqy": "510,000", "stkqy_irds": "510,000",
            "stkrt": "5.10", "stkrt_irds": "5.10",
            "report_resn": "장내매수에 따른 5% 이상 신규보고",
        },
        {
            "rcept_no": "20261001000001", "rcept_dt": "20261001",
            "corp_code": "00999999", "corp_name": "테스트전자",
            "repror": "얼라인파트너스자산운용",
            "stkqy": "620,000", "stkqy_irds": "110,000",
            "stkrt": "6.20", "stkrt_irds": "1.10",
            "report_resn": "장내매수에 따른 보유주식수 증가",
        },
        {
            "rcept_no": "20261102000001", "rcept_dt": "20261102",
            "corp_code": "00999999", "corp_name": "테스트전자",
            "repror": "얼라인파트너스자산운용",
            "stkqy": "730,000", "stkqy_irds": "110,000",
            "stkrt": "7.30", "stkrt_irds": "1.10",
            "report_resn": "장내매수에 따른 보유주식수 증가 및 보유목적 변경(단순투자→경영권 영향)",
            "report_nm": "주식등의대량보유상황보고서(일반)",
        },
    ]
    collector = _live_collector(monkeypatch, list_rows, {"00999999": major_rows})

    events = collector.collect(since=datetime(2026, 8, 1))

    assert len(events) == 1
    evt = events[0]
    assert evt.source_event_uid == "20261102000001"
    assert "보유비율 7.3%" in evt.evidence_text

    analysis = evt.raw_payload["five_pct_analysis"]
    # S1 행동주의 4 + S2 (지분확대 2 + 3연속 매집 4) + S3 목적상향 5
    # + S6 장내매수 원천 2 = 17. 가격 데이터가 없어 평단 안전마진은 미산출.
    assert analysis["alpha_score"] == 17
    assert analysis["factor_scores"] == {
        "s1_investor": 4,
        "s2_accumulation": 6,
        "s3_purpose": 5,
        "s4_new_entry": 0,
        "s5_milestone_10pct": 0,
        "s6_price_margin": 2,
        "s7_exit_risk": 0,
    }
    assert analysis["investor_class"] == "행동주의"
    assert analysis["purpose_prev"] == "단순투자"
    assert analysis["purpose_current"] == "경영권 영향"
    assert analysis["accumulation_count"] == 3
    assert analysis["first_entry_dt"] == "2026-09-01"
    assert any(
        entry["reason"] == "미산출(가격 데이터 필요)"
        for entry in analysis["score_breakdown"]
    )


def test_five_pct_collector_merges_amendment_filings(monkeypatch):
    list_rows = [
        {
            "corp_code": "00999999",
            "corp_name": "테스트전자",
            "stock_code": "123456",
            "report_nm": "[기재정정]주식등의대량보유상황보고서(일반)",
            "rcept_no": "20261102000002",
            "rcept_dt": "20261102",
            "flr_nm": "홍길동",
        }
    ]
    major_rows = [
        {
            "rcept_no": "20261102000001", "rcept_dt": "20261102",
            "corp_code": "00999999", "corp_name": "테스트전자",
            "repror": "홍길동",
            "stkqy": "600,000", "stkqy_irds": "600,000",
            "stkrt": "6.00", "stkrt_irds": "6.00",
            "report_resn": "장내매수에 따른 5% 이상 신규보고",
            "report_nm": "주식등의대량보유상황보고서(일반)",
        },
        {
            "rcept_no": "20261102000002", "rcept_dt": "20261102",
            "corp_code": "00999999", "corp_name": "테스트전자",
            "repror": "홍길동",
            "stkqy": "600,000", "stkqy_irds": "600,000",
            "stkrt": "6.00", "stkrt_irds": "6.00",
            "report_resn": "장내매수에 따른 5% 이상 신규보고",
            "report_nm": "[기재정정]주식등의대량보유상황보고서(일반)",
        },
    ]
    collector = _live_collector(monkeypatch, list_rows, {"00999999": major_rows})

    events = collector.collect(since=datetime(2026, 11, 1))

    # 원본과 정정본은 하나의 이벤트로 병합되고, 최신 정정본이 남는다.
    assert len(events) == 1
    assert events[0].source_event_uid == "20261102000002"
    assert len(events[0].raw_payload["history"]) == 1


def test_five_pct_collector_caps_majorstock_corps_per_run(tmp_path):
    corps = [
        {
            "corp_code": f"{i:08d}",
            "corp_name": f"테스트기업{i}",
            "stock_code": f"{i:06d}",
            "report_nm": "주식등의대량보유상황보고서(일반)",
            "rcept_no": f"20261105{i:06d}",
            "rcept_dt": "20261105",
            "flr_nm": "홍길동",
        }
        for i in range(65)
    ]
    fixture_path = tmp_path / "five_pct_many.json"
    fixture_path.write_text(
        json.dumps({"list": corps}, ensure_ascii=False), encoding="utf-8"
    )
    collector = DartFivePctCollector(fixture_path=fixture_path)

    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 60
