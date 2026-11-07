"""Integration tests: DISCLOSED document enrichment in DartFivePctCollector.

The collector parses only each corp's single latest filing document
(event_radar.dart_document) and lands the disclosed weighted-average
price in that filing's score_input (Priority 1), so the pipeline's
five_pct_pricing replay scores S6 against the real disclosed price
instead of a VWAP estimate.
"""

import json
from datetime import datetime
from pathlib import Path

from event_radar.collectors.dart_five_pct import DartFivePctCollector
from event_radar.five_pct_rules import evaluate_signal_score


FIXTURE = Path(__file__).parent.parent / "fixtures" / "dart" / "sample_five_pct.json"


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _live_collector(monkeypatch, list_rows, majorstock_by_corp, **kwargs):
    collector = DartFivePctCollector(api_key="TEST_KEY", **kwargs)
    list_payload = {"status": "000", "total_page": 1, "list": list_rows}

    def mock_get(url, *args, **mock_kwargs):
        if "majorstock" in url:
            corp_code = mock_kwargs.get("params", {}).get("corp_code")
            rows = majorstock_by_corp.get(corp_code)
            if rows is None:
                return FakeResponse({"status": "013", "list": []})
            return FakeResponse({"status": "000", "list": rows})
        if "elestock" in url:
            return FakeResponse({"status": "013", "list": []})
        return FakeResponse(list_payload)

    monkeypatch.setattr(collector.session, "get", mock_get)
    return collector


# 행동주의 보고자(얼라인파트너스)의 3건 이력 — 기존 스코어링 테스트와 같은
# 패턴으로, 최신 공시(20261102000001)의 majorstock 목적은 '경영권 영향'.
LIST_ROWS = [
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
MAJOR_ROWS = [
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

DISCLOSED_SOURCE = "DISCLOSED: 원문 제3부 세부변동내역 가중평균(110,000주)"


def _detail(**overrides):
    detail = {
        "ok": True,
        "weighted_avg_price": 10000,
        "price_source": DISCLOSED_SOURCE,
        "curr_purpose": "경영권 영향",  # majorstock 목적과 동일
        "unit_prices": ["10,000원 (수량가중평균)"],
        "total_shares": 110000,
    }
    detail.update(overrides)
    return detail


def test_collector_applies_disclosed_price_to_latest_filing(monkeypatch):
    calls = []

    def fake_fetcher(rcept_no):
        calls.append(rcept_no)
        return _detail()

    collector = _live_collector(
        monkeypatch, LIST_ROWS, {"00999999": MAJOR_ROWS},
        document_fetcher=fake_fetcher,
    )
    events = collector.collect(since=datetime(2026, 8, 1))

    assert len(events) == 1
    # 종목당 1회, 최신 공시에 대해서만 문서를 읽는다.
    assert calls == ["20261102000001"]

    analysis = events[0].raw_payload["five_pct_analysis"]
    score_input = analysis["score_input"]
    assert score_input["est_avg_price"] == 10000
    assert score_input["price_source"] == DISCLOSED_SOURCE
    # 문서 목적이 majorstock과 같으면 교정 기록은 남지 않는다.
    assert "purpose_source" not in analysis
    # 수집 시점에는 현재가가 없어 안전마진 점수는 아직 없고, 가격 미산출
    # 플레이스홀더도 사라진다 (평단이 실렸으므로). 나머지 점수는 기존과 동일.
    assert analysis["alpha_score"] == 17
    assert not any(
        entry["reason"] == "미산출(가격 데이터 필요)"
        for entry in analysis["score_breakdown"]
    )

    # 파이프라인(five_pct_pricing)이 하는 재채점을 그대로 재현: 현재가를
    # 평단보다 13% 낮게 넣으면 S6 안전마진이 DISCLOSED 단가 기준으로 붙는다.
    replayed = evaluate_signal_score({**score_input, "current_price": 8700})
    assert replayed["factor_scores"]["s6_price_margin"] == 4  # 원천 2 + 안전마진 2
    margin_entries = [
        entry
        for entry in replayed["breakdown"]
        if entry["strategy"] == "전략 6 (세력 평단 안전마진)"
    ]
    assert len(margin_entries) == 1
    assert margin_entries[0]["points"] == 2
    assert "DISCLOSED:" in margin_entries[0]["reason"]


def test_collector_document_purpose_overrides_majorstock(monkeypatch):
    def fake_fetcher(rcept_no):
        return _detail(curr_purpose="단순투자")

    collector = _live_collector(
        monkeypatch, LIST_ROWS, {"00999999": MAJOR_ROWS},
        document_fetcher=fake_fetcher,
    )
    events = collector.collect(since=datetime(2026, 8, 1))

    analysis = events[0].raw_payload["five_pct_analysis"]
    assert analysis["purpose_current"] == "단순투자"
    assert analysis["purpose_source"] == "DOCUMENT"
    assert analysis["score_input"]["curr_purpose"] == "단순투자"


def test_collector_document_failure_leaves_filing_untouched(monkeypatch):
    def failing_fetcher(rcept_no):
        raise ConnectionError("document viewer unreachable")

    collector = _live_collector(
        monkeypatch, LIST_ROWS, {"00999999": MAJOR_ROWS},
        document_fetcher=failing_fetcher,
    )
    events = collector.collect(since=datetime(2026, 8, 1))

    assert len(events) == 1
    analysis = events[0].raw_payload["five_pct_analysis"]
    assert analysis["score_input"]["est_avg_price"] is None
    assert analysis["alpha_score"] == 17
    assert any(
        entry["reason"] == "미산출(가격 데이터 필요)"
        for entry in analysis["score_breakdown"]
    )


def test_collector_parses_fixture_documents_end_to_end(tmp_path):
    fixture_data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    main_html = """
    <script>
      viewDoc('20261105000111', '10000001', '1', '0', '5000', 'dart4.xsd');
    </script>
    """
    detail_html = """
    <table>
      <tr>
        <td>국민연금공단</td><td>1950.01.01</td><td>2026.11.04</td><td>장내매수</td>
        <td>보통주</td><td>446,889,456</td><td>1,234,000</td><td>448,123,456</td>
        <td>58,000</td><td>-</td>
      </tr>
    </table>
    """
    fixture_data["documents"] = {
        "20261105000111": {
            "main_html": main_html,
            "viewer_htmls": [detail_html],
        }
    }
    fixture_path = tmp_path / "five_pct_with_documents.json"
    fixture_path.write_text(
        json.dumps(fixture_data, ensure_ascii=False), encoding="utf-8"
    )

    collector = DartFivePctCollector(fixture_path=fixture_path)
    events = collector.collect(since=datetime(2026, 11, 1))

    evt = [e for e in events if e.primary_ticker == "005930"][0]
    score_input = evt.raw_payload["five_pct_analysis"]["score_input"]
    assert score_input["est_avg_price"] == 58000
    assert score_input["price_source"] == (
        "DISCLOSED: 원문 제3부 세부변동내역 가중평균(1,234,000주)"
    )
