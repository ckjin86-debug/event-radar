"""Tests for SecFivePctCollector (US SEC Schedule 13D/13G 5% collector).

Mirrors the original extension's SEC pipeline: EDGAR full-text search
discovery (efts search-index) -> primary_doc.xml verification -> the
shared seven-strategy scoring engine (five_pct_rules).
"""

import importlib.util
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from event_radar.collectors.sec_five_pct import (
    SEC_13DG_FORMS,
    SEC_EFTS_SEARCH_URL,
    SecFivePctCollector,
)
from event_radar.export import export_site_data
from event_radar.models import Event


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "sec" / "sample_five_pct.json"
)
SINCE = datetime(2026, 11, 1)


def _collect(fixture_path=FIXTURE_PATH):
    collector = SecFivePctCollector(fixture_path=fixture_path, request_interval=0)
    return collector.collect(SINCE)


def _by_uid(events):
    return {event.source_event_uid: event for event in events}


class TestSecFivePctCollector:
    def test_collect_skips_filing_without_percent_of_class(self):
        events = _collect()

        assert len(events) == 4
        # 0005678901-26-000005 has no percentOfClass in its primary doc:
        # the original skipped such filings instead of guessing a stake.
        assert "0005678901-26-000005" not in _by_uid(events)

    def test_events_carry_us_five_pct_shape(self):
        event = _by_uid(_collect())["0001234567-26-000001"]

        assert event.source_name == "SEC_13DG"
        assert event.source_kind == "REGULATOR"
        assert event.event_type == "5PCT_OWNERSHIP"
        assert event.country == "US"
        assert event.status == "CONFIRMED"
        assert event.primary_ticker == "ACME"
        assert event.primary_company == "Acme Robotics, Inc."
        assert event.announced_at == datetime(2026, 11, 5)
        assert event.event_date == date(2026, 11, 5)
        assert event.source_url.endswith("0001234567-26-000001-index.html")
        assert "보유비율 7.5%" in event.evidence_text
        assert "보유주식수 1,500,000주" in event.evidence_text

    def test_13d_new_filing_scores_purpose_upgrade(self):
        event = _by_uid(_collect())["0001234567-26-000001"]
        analysis = event.raw_payload["five_pct_analysis"]

        # S1 activist (Elliott) +4, S2 genuine accumulation +3,
        # S3 purpose upgrade 단순투자 -> 경영권 영향 +5, S4 new entry +2,
        # S6 verified open-market source +2.
        assert analysis["alpha_score"] == 16
        assert analysis["factor_scores"] == {
            "s1_investor": 4,
            "s2_accumulation": 3,
            "s3_purpose": 5,
            "s4_new_entry": 2,
            "s5_milestone_10pct": 0,
            "s6_price_margin": 2,
            "s7_exit_risk": 0,
        }
        assert analysis["investor_type"] == "ACTIVIST"
        assert analysis["purpose_prev"] == "단순투자"
        assert analysis["purpose_current"] == "경영권 영향"
        assert analysis["accumulation_count"] == 1
        # Primary category follows the original's priority (purpose change
        # first); the HIGH tier is score-driven (>= 5) at export time.
        assert analysis["category"] == "PURPOSE"
        assert set(analysis["categories"]) == {"NEW", "PURPOSE"}
        # DERIVED average price from Item 3 fundsSource ($15,000,000 / 1.5M shares).
        assert analysis["score_input"]["est_avg_price"] == 10.0
        assert analysis["score_input"]["price_source"].startswith("DERIVED")
        assert "missing_fields" not in analysis
        history = event.raw_payload["history"]
        assert len(history) == 1
        assert history[0]["hold_stock_rt"] == 7.5

    def test_13g_passive_filer_scores_noise_zero(self):
        event = _by_uid(_collect())["0002345678-26-000002"]
        analysis = event.raw_payload["five_pct_analysis"]

        # BlackRock is classified passive in the shared investor dictionary:
        # category NOISE with a hard zero score, exactly as in the original.
        assert analysis["alpha_score"] == 0
        assert analysis["category"] == "NOISE"
        assert analysis["investor_type"] == "PASSIVE"
        assert analysis["purpose_current"] == "단순투자"
        assert event.primary_ticker == "BETA"

    def test_amendment_uses_ticker_map_and_records_missing_fields(self):
        event = _by_uid(_collect())["0003456789-26-000003"]
        analysis = event.raw_payload["five_pct_analysis"]

        # No "(TICKER)" suffix in the display name: the SEC company_tickers
        # mapping supplies both ticker and canonical company title.
        assert event.primary_ticker == "GNET"
        assert event.primary_company == "Gamma Networks, Inc."
        # Amendment: no stake delta, no new entry; 13D purpose is maintained.
        assert analysis["score_input"]["stk_rt_var"] == 0
        assert analysis["accumulation_count"] == 0
        # S1 activist (Pershing Square) +4, S3 maintained control purpose +3.
        assert analysis["alpha_score"] == 7
        assert analysis["factor_scores"]["s3_purpose"] == 3
        # aggregateAmountOwned / fundsSource were absent from the XML.
        assert analysis["score_input"]["hold_stock_cnt"] == "-"
        assert "aggregateAmountOwned" in analysis["missing_fields"]
        assert "fundsSource" in analysis["missing_fields"]

    def test_ticker_mapping_failure_degrades_to_cik_identifier(self):
        event = _by_uid(_collect())["0004567890-26-000004"]
        analysis = event.raw_payload["five_pct_analysis"]

        # No ticker in the display name and no mapping entry: the filing is
        # still collected, identified by CIK, with the gap recorded.
        assert event.primary_ticker == "CIK4567890"
        assert event.primary_company == "Delta Retail Group, Inc."
        assert "ticker" in analysis["missing_fields"]
        # reportingPersonName absent from the XML: fell back to the filer
        # name from the EDGAR display names.
        assert "reportingPersonName" in analysis["missing_fields"]
        assert analysis["reporter"] == "Small Holder LLC"

    def test_graceful_empty_list_when_search_fails(self, monkeypatch):
        collector = SecFivePctCollector(fixture_path=None, request_interval=0)

        def boom(*args, **kwargs):
            raise ConnectionError("network down")

        monkeypatch.setattr(collector.session, "get", boom)
        assert collector.collect(SINCE) == []


class _FakeResponse:
    def __init__(self, *, json_data=None, text=""):
        self.status_code = 200
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


def test_live_requests_follow_edgar_search_pattern(monkeypatch):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    first_hit = fixture["efts"]["hits"]["hits"][0]
    efts_payload = {"hits": {"hits": [first_hit]}}
    primary_xml = fixture["primary_docs"][first_hit["_source"]["adsh"]]

    collector = SecFivePctCollector(fixture_path=None, request_interval=0)
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers})
        if url == SEC_EFTS_SEARCH_URL:
            return _FakeResponse(json_data=efts_payload)
        if url.endswith("company_tickers.json"):
            return _FakeResponse(json_data={})
        if url.endswith("/primary_doc.xml"):
            return _FakeResponse(text=primary_xml)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(collector.session, "get", fake_get)
    events = collector.collect(SINCE)

    assert len(events) == 1
    assert events[0].primary_ticker == "ACME"

    search_call = calls[0]
    assert search_call["params"]["forms"] == SEC_13DG_FORMS
    assert "SC 13D/A" in search_call["params"]["forms"]
    assert search_call["params"]["dateRange"] == "custom"
    assert search_call["params"]["startdt"] == "2026-11-01"
    assert search_call["headers"]["Accept"] == "application/json"
    # SEC fair access: a descriptive User-Agent is always sent.
    assert "EventRadarAdmin" in collector.session.headers["User-Agent"]

    doc_urls = [c["url"] for c in calls if c["url"].endswith("/primary_doc.xml")]
    assert doc_urls == [
        "https://www.sec.gov/Archives/edgar/data/1234567/"
        "000123456726000001/primary_doc.xml"
    ]


def test_collect_script_registers_sec_five_pct_outside_fast_refresh(tmp_path):
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "collect.py"
    spec = importlib.util.spec_from_file_location("collect_script_sec", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    names = [c.source_name for c in module.build_collectors(tmp_path)]
    assert "SEC_13DG" in names
    fast_names = [
        c.source_name for c in module.build_collectors(tmp_path, fast_refresh=True)
    ]
    assert "SEC_13DG" not in fast_names


def test_us_five_pct_row_exports_with_country_and_source(tmp_path):
    raw = _by_uid(_collect())["0001234567-26-000001"]
    analysis = raw.raw_payload["five_pct_analysis"]
    now = datetime(2026, 11, 7, 9, 0, 0)
    event = Event(
        event_id="US_SEC_13DG_0001234567-26-000001",
        country=raw.country,
        event_type=raw.event_type,
        event_name=raw.event_name,
        primary_ticker=raw.primary_ticker,
        primary_company=raw.primary_company,
        announced_at=raw.announced_at,
        event_date=raw.event_date,
        event_time_context=raw.event_time_context,
        status=raw.status,
        source_kind=raw.source_kind,
        source_name=raw.source_name,
        source_url=raw.source_url,
        source_event_uid=raw.source_event_uid,
        evidence_text=raw.evidence_text,
        ingest_mode=raw.ingest_mode,
        first_seen_at=now,
        last_seen_at=now,
        needs_review=False,
        five_pct_analysis=analysis,
    )

    export_site_data(
        events=[event],
        revisions=[],
        event_securities={},
        event_scores={},
        event_returns_df=None,
        strategy_results={},
        backtest_summaries={},
        output_dir=tmp_path,
        collector_status={},
        now=now,
    )

    five = json.loads((tmp_path / "five_pct.json").read_text(encoding="utf-8"))
    assert len(five) == 1
    row = five[0]
    assert row["country"] == "US"
    assert row["source_name"] == "SEC_13DG"
    assert row["alpha_score"] == 16
    assert row["insight"]["tier"] == "HIGH"
    # 가격 보강(five_pct_pricing)은 KR 전용 호출이라 US 행에는 가격 키가
    # 붙지 않는다 — DERIVED 단가는 score_input 안에만 남는다 (KR 수집 직후와 동일).
    assert row.get("est_avg_price") is None
    assert row.get("current_price") is None
    assert row.get("price_gap_pct") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
