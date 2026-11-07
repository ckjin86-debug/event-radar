"""Tests for the SEC 13D/13G five-percent collector.

The fixture (tests/fixtures/sec/sample_five_pct.json) is built from REAL
EDGAR filings captured 2026-11-07 (efts search hits + primary_doc.xml +
company_tickers subset), because the edgartools XML parser rightfully
rejects hand-made schema-incomplete documents:

- 0001753926-26-002072  SCHEDULE 13D/A  ClearOne (CLRO) — Bagley, 6.5%
- 0001753926-26-002067  SCHEDULE 13D/A  CDT Equity (CDT) — Corvus, 16.8%
  (three reporting persons; joint totals are 22.1% / 2,064,698 shares —
  the row must use reporting_persons[0], never the totals)
- 0001493152-26-050478  SCHEDULE 13D    Silvia (SVIA) — new entry, 5.6%
- 0001905106-26-000174  SCHEDULE 13G/A  Dynamix (DYNC) — Meteora, 9.15%
  (13G XML uses <classPercent>, which the legacy regex parser could not
  read at all — every real 13G used to be silently skipped)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from event_radar.collectors.sec_five_pct import SecFivePctCollector


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "sec"
    / "sample_five_pct.json"
)

SINCE = datetime(2026, 11, 1)


def _collect(fixture_path=FIXTURE_PATH):
    collector = SecFivePctCollector(fixture_path=fixture_path, request_interval=0)
    return collector.collect(SINCE)


def _write_tmp_fixture(tmp_path, mutate) -> Path:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    mutate(fixture)
    path = tmp_path / "five_pct_fixture.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return path


def test_collect_uses_fixture_and_scores_with_original_seven_strategies():
    events = _collect()

    assert len(events) == 4
    by_uid = {event.source_event_uid: event for event in events}

    clro = by_uid["0001753926-26-002072"]
    assert clro.source_name == "SEC_13DG"
    assert clro.primary_ticker == "CLRO"
    assert clro.primary_company == "CLEARONE INC"
    assert clro.announced_at.date().isoformat() == "2026-11-06"
    clro_analysis = clro.raw_payload["five_pct_analysis"]
    assert clro_analysis["reporter"] == "BAGLEY EDWARD D"
    assert clro_analysis["score_input"]["hold_stock_rt"] == 6.5
    assert clro_analysis["score_input"]["hold_stock_cnt"] == "173,511"
    assert clro_analysis["alpha_score"] == 3
    assert clro_analysis["factor_scores"] == {
        "s1_investor": 0,
        "s2_accumulation": 0,
        "s3_purpose": 3,
        "s4_new_entry": 0,
        "s5_milestone_10pct": 0,
        "s6_price_margin": 0,
        "s7_exit_risk": 0,
    }
    assert clro_analysis["category"] == "PURPOSE"

    svia = by_uid["0001493152-26-050478"]
    svia_analysis = svia.raw_payload["five_pct_analysis"]
    assert svia.primary_ticker == "SVIA"
    assert svia_analysis["reporter"] == "Shain Noor"
    assert svia_analysis["score_input"]["hold_stock_rt"] == 5.6
    assert svia_analysis["score_input"]["stk_rt_var"] == 5.6
    assert svia_analysis["purpose_prev"] == "단순투자"
    assert svia_analysis["purpose_current"] == "경영권 영향"
    assert svia_analysis["accumulation_count"] == 1
    assert svia_analysis["alpha_score"] == 5
    assert svia_analysis["factor_scores"]["s3_purpose"] == 5
    assert svia_analysis["category"] == "PURPOSE"
    assert "보유비율 증감 5.6%p" in svia.evidence_text

    dync = by_uid["0001905106-26-000174"]
    dync_analysis = dync.raw_payload["five_pct_analysis"]
    assert dync.primary_ticker == "DYNC"
    assert dync_analysis["reporter"] == "Meteora Capital, LLC"
    assert dync_analysis["score_input"]["hold_stock_rt"] == 9.15
    assert dync_analysis["score_input"]["hold_stock_cnt"] == "1,518,428"
    assert dync_analysis["investor_type"] == "PEF_SI"
    assert dync_analysis["alpha_score"] == 2
    assert dync_analysis["category"] == "ALL"
    assert "Passive Ownership" in dync.evidence_text


def test_first_reporting_person_wins_over_joint_totals():
    events = _collect()
    by_uid = {event.source_event_uid: event for event in events}

    corvus = by_uid["0001753926-26-002067"]
    analysis = corvus.raw_payload["five_pct_analysis"]
    assert corvus.primary_ticker == "CDT"
    assert analysis["reporter"] == "Corvus Capital Ltd."
    # reporting_persons[0]: 16.8% / 1,565,080 — NOT the joint totals
    # (22.1% / 2,064,698) summed over all three reporting persons.
    assert analysis["score_input"]["hold_stock_rt"] == 16.8
    assert analysis["score_input"]["hold_stock_cnt"] == "1,565,080"
    assert analysis["alpha_score"] == 1
    assert analysis["factor_scores"]["s3_purpose"] == 3


def test_filing_without_readable_percent_is_skipped(tmp_path):
    adsh = "0001753926-26-002072"

    def mutate(fixture):
        xml = fixture["primary_docs"][adsh]
        # Remove the percent from the real document: edgartools then
        # reports percent_of_class as unreported, and the filing must be
        # skipped (the legacy parser skipped filings whose percent was
        # unreadable instead of guessing a stake).
        stripped = re.sub(
            r"<percentOfClass>[\s\S]*?</percentOfClass>", "", xml, count=1
        )
        assert stripped != xml
        fixture["primary_docs"][adsh] = stripped
        fixture["efts"]["hits"]["hits"] = [
            hit
            for hit in fixture["efts"]["hits"]["hits"]
            if hit["_source"]["adsh"] == adsh
        ]

    assert _collect(_write_tmp_fixture(tmp_path, mutate)) == []


def test_ticker_falls_back_to_company_tickers_map(tmp_path):
    def mutate(fixture):
        for hit in fixture["efts"]["hits"]["hits"]:
            if hit["_source"]["adsh"] == "0001753926-26-002067":
                # Strip the "(CDT)" suffix so only the CIK map resolves it.
                hit["_source"]["display_names"][0] = (
                    "CDT Equity Inc.  (CIK 0001896212)"
                )

    events = _collect(_write_tmp_fixture(tmp_path, mutate))
    by_uid = {event.source_event_uid: event for event in events}
    # company_tickers lists CIK 1896212 as CDT first (then CDTTW); the
    # map keeps the first record per CIK.
    assert by_uid["0001753926-26-002067"].primary_ticker == "CDT"


def test_unstructured_document_is_skipped_not_fatal():
    collector = SecFivePctCollector(request_interval=0)
    assert collector._parse_primary_doc("<html>not a schedule</html>") is None
    assert collector._parse_primary_doc("") is None
    assert collector._parse_primary_doc(None) is None


def test_edgartools_missing_is_a_hard_failure(monkeypatch):
    import event_radar.collectors.sec_five_pct as module

    monkeypatch.setattr(module, "Schedule13D", None)
    monkeypatch.setattr(module, "Schedule13G", None)
    collector = SecFivePctCollector(request_interval=0)
    with pytest.raises(RuntimeError):
        collector._parse_primary_doc("<edgarSubmission/>", form="SCHEDULE 13D")
