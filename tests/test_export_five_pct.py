import json
from datetime import date, datetime

from event_radar.export import export_site_data
from event_radar.models import Event, EventSecurity
from event_radar.scoring import ScoreResult


NOW = datetime(2026, 11, 3, 10, 0, 0)


def _event(
    event_id: str,
    event_type: str,
    *,
    source_name: str = "DART",
    event_date: date = date(2026, 11, 20),
    evidence_text: str = "test",
) -> Event:
    return Event(
        event_id=event_id,
        country="KR",
        event_type=event_type,
        event_name=f"테스트 {event_type}",
        primary_ticker="123456",
        primary_company="테스트기업",
        announced_at=NOW,
        event_date=event_date,
        event_time_context="DATE_ONLY",
        status="CONFIRMED",
        source_kind="REGULATOR",
        source_name=source_name,
        source_url="https://example.com",
        source_event_uid=event_id,
        evidence_text=evidence_text,
        ingest_mode="AUTO",
        first_seen_at=NOW,
        last_seen_at=NOW,
        needs_review=False,
    )


def _five_event(event_id: str, *, event_date: date, evidence_text: str = "주식등의대량보유상황보고서(일반)", five_pct_analysis: dict | None = None) -> Event:
    event = _event(
        event_id,
        "5PCT_OWNERSHIP",
        source_name="DART_5PCT",
        event_date=event_date,
        evidence_text=evidence_text,
    )
    if five_pct_analysis is not None:
        event.five_pct_analysis = five_pct_analysis
    return event


def _export(tmp_path, events, event_securities=None, event_scores=None):
    export_site_data(
        events=events,
        revisions=[],
        event_securities=event_securities or {},
        event_scores=event_scores or {},
        event_returns_df=None,
        strategy_results={},
        backtest_summaries={},
        output_dir=tmp_path,
        collector_status={},
        now=NOW,
    )
    return (
        json.loads((tmp_path / "events.json").read_text(encoding="utf-8")),
        json.loads((tmp_path / "five_pct.json").read_text(encoding="utf-8")),
        json.loads((tmp_path / "event_details.json").read_text(encoding="utf-8")),
    )


def test_five_pct_events_are_split_out_of_events_json(tmp_path):
    scheduled = _event("capex-1", "CAPEX_FINANCING")
    filing = _five_event(
        "five-1",
        event_date=date(2026, 11, 2),
        evidence_text="주식등의대량보유상황보고서(일반) · 대표보고자 국민연금공단 · 보유비율 7.51%",
    )

    events, five, details = _export(tmp_path, [scheduled, filing])

    assert [row["event_id"] for row in events] == ["capex-1"]
    assert set(details) == {"capex-1"}

    assert len(five) == 1
    row = five[0]
    assert row["event_id"] == "five-1"
    assert row["event_type"] == "5PCT_OWNERSHIP"
    assert row["source_name"] == "DART_5PCT"
    assert row["event_date"] == "2026-11-02"
    assert row["window_start"] == "2026-11-02"
    assert row["window_end"] == "2026-11-02"
    assert row["status"] == "CONFIRMED"
    # No resolved securities: the filing's subject company is the direct party.
    assert row["relation_grade"] == "A"
    assert row["relation_type"] == "DIRECT"
    assert row["related_securities"][0]["ticker"] == "123456"
    assert row["related_securities"][0]["name"] == "테스트기업"
    # No event score available: fall back to the relation score.
    assert row["event_score"] == row["relation_score"] == 100
    assert row["insight"]["summary"] == filing.evidence_text
    assert row["insight"]["score"] == row["event_score"]


def test_five_pct_export_uses_resolved_security_and_event_score(tmp_path):
    filing = _five_event("five-2", event_date=date(2026, 11, 2))
    security = EventSecurity(
        event_id="five-2",
        ticker="123456",
        relation_grade="B",
        relation_score=77,
        relation_type="DIRECT",
        evidence_text="직접 당사자",
        evidence_source="DART_5PCT",
        source_url="https://example.com",
        ingest_mode="AUTO",
        company_name="테스트기업",
    )
    score = ScoreResult(
        total_score=55,
        schedule_points=10,
        relation_points=20,
        edge_points=10,
        robustness_points=10,
        setup_points=5,
    )

    _, five, _ = _export(
        tmp_path,
        [filing],
        event_securities={"five-2": [security]},
        event_scores={"five-2": score},
    )

    assert len(five) == 1
    row = five[0]
    assert row["relation_grade"] == "B"
    assert row["relation_score"] == 77
    assert row["event_score"] == 55
    assert row["related_securities"][0]["name"] == "테스트기업"
    assert row["related_securities"][0]["relation_score"] == 77


def _analysis(alpha_score: int) -> dict:
    return {
        "alpha_score": alpha_score,
        "score_breakdown": [
            {"strategy": "전략 1 (주체 가중치)", "reason": "행동주의 핵심 주체 (얼라인파트너스자산운용)", "points": 4},
            {"strategy": "전략 2 (연속 매집)", "reason": "공식 이력 기준 3회 연속 실제 보유주식수 증가 확인", "points": 4},
            {"strategy": "전략 6 (세력 평단 안전마진)", "reason": "미산출(가격 데이터 필요)", "points": 0},
        ],
        "investor_class": "행동주의",
        "purpose_prev": "단순투자",
        "purpose_current": "경영권 영향",
        "accumulation_count": 3,
        "freshness": "CURRENT",
    }


def test_five_pct_export_uses_collector_alpha_analysis(tmp_path):
    filing = _five_event(
        "five-alpha",
        event_date=date(2026, 11, 2),
        five_pct_analysis=_analysis(8),
    )
    # Even a generic pipeline score exists, the alpha score wins.
    score = ScoreResult(
        total_score=55,
        schedule_points=10,
        relation_points=20,
        edge_points=10,
        robustness_points=10,
        setup_points=5,
    )

    _, five, _ = _export(tmp_path, [filing], event_scores={"five-alpha": score})

    assert len(five) == 1
    row = five[0]
    assert row["alpha_score"] == 8
    assert row["event_score"] == 8
    assert row["insight"]["score"] == 8
    assert row["insight"]["tier"] == "HIGH"
    # Summary is composed from the scored breakdown reasons only.
    assert row["insight"]["summary"] == (
        "행동주의 핵심 주체 (얼라인파트너스자산운용)"
        " · 공식 이력 기준 3회 연속 실제 보유주식수 증가 확인"
    )
    assert row["score_breakdown"] == _analysis(8)["score_breakdown"]
    assert row["investor_class"] == "행동주의"
    assert row["purpose_prev"] == "단순투자"
    assert row["purpose_current"] == "경영권 영향"
    assert row["accumulation_count"] == 3
    assert row["freshness"] == "CURRENT"


def test_five_pct_export_alpha_tier_thresholds(tmp_path):
    filings = [
        _five_event("five-t5", event_date=date(2026, 11, 2), five_pct_analysis=_analysis(5)),
        _five_event("five-t1", event_date=date(2026, 11, 2), five_pct_analysis=_analysis(1)),
        _five_event("five-t0", event_date=date(2026, 11, 2), five_pct_analysis=_analysis(0)),
        _five_event("five-tm1", event_date=date(2026, 11, 2), five_pct_analysis=_analysis(-1)),
        _five_event("five-tm2", event_date=date(2026, 11, 2), five_pct_analysis=_analysis(-2)),
    ]

    _, five, _ = _export(tmp_path, filings)

    tiers = {row["event_id"]: row["insight"]["tier"] for row in five}
    assert tiers == {
        "five-t5": "HIGH",
        "five-t1": "POSITIVE",
        "five-t0": "NEUTRAL",
        "five-tm1": "NEUTRAL",
        "five-tm2": "RISK",
    }


def test_five_pct_export_without_analysis_keeps_legacy_fields(tmp_path):
    filing = _five_event("five-plain", event_date=date(2026, 11, 2))

    _, five, _ = _export(tmp_path, [filing])

    row = five[0]
    assert row["alpha_score"] is None
    assert row["score_breakdown"] == []
    assert row["investor_class"] is None
    assert row["purpose_prev"] is None
    assert row["purpose_current"] is None
    assert row["accumulation_count"] is None
    assert row["freshness"] is None
    assert row["insight"]["tier"] == "WATCH"


def test_five_pct_export_sorted_by_date_desc_and_empty_when_no_filings(tmp_path):
    older = _five_event("five-old", event_date=date(2026, 10, 30))
    newer = _five_event("five-new", event_date=date(2026, 11, 2))

    _, five, _ = _export(tmp_path, [older, newer])
    assert [row["event_id"] for row in five] == ["five-new", "five-old"]

    events, five_empty, _ = _export(tmp_path / "plain", [_event("capex-1", "CAPEX_FINANCING")])
    assert [row["event_id"] for row in events] == ["capex-1"]
    assert five_empty == []
