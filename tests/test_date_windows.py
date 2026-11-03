import json
from datetime import date, datetime

from event_radar.models import EventSecurity, RawEvent
from event_radar.normalize import normalize_event
from event_radar.pipeline import load_canonical_events, save_canonical_events
from event_radar.export import export_site_data


def _raw(**overrides):
    payload = dict(
        source_name="NEWS_FUTURE",
        source_kind="SECONDARY",
        source_event_uid="news-window-1",
        source_url="https://example.com/news/1",
        country="KR",
        primary_ticker="005930",
        primary_company="삼성전자",
        event_type="PLANT_OPERATION",
        event_name="삼성전자 내달 신규 라인 가동",
        announced_at=datetime(2026, 11, 3, 9, 0, 0),
        event_date=date(2026, 12, 1),
        event_time_context="DATE_ONLY",
        status="EXPECTED",
        evidence_text="내달 신규 라인 가동 예정",
        ingest_mode="AUTO",
    )
    payload.update(overrides)
    return RawEvent(**payload)


def test_month_window_survives_normalize_csv_and_site_export(tmp_path):
    raw = _raw(
        date_precision="MONTH",
        window_start=date(2026, 12, 1),
        window_end=date(2026, 12, 31),
    )
    event = normalize_event(raw, now=datetime(2026, 11, 3, 10, 0, 0))

    assert event.date_precision == "MONTH"
    assert event.window_start == date(2026, 12, 1)
    assert event.window_end == date(2026, 12, 31)

    csv_path = tmp_path / "events.csv"
    save_canonical_events([event], csv_path)
    loaded = load_canonical_events(csv_path)

    assert loaded[0].date_precision == "MONTH"
    assert loaded[0].window_start == date(2026, 12, 1)
    assert loaded[0].window_end == date(2026, 12, 31)

    direct = EventSecurity(
        event_id=loaded[0].event_id,
        ticker="005930",
        relation_grade="A",
        relation_score=100,
        relation_type="DIRECT",
        evidence_text="직접 당사자",
    )

    out = tmp_path / "site"
    export_site_data(
        events=loaded,
        revisions=[],
        event_securities={loaded[0].event_id: [direct]},
        event_scores={},
        event_returns_df=None,
        strategy_results={},
        backtest_summaries={},
        output_dir=out,
        collector_status={},
        now=datetime(2026, 11, 3, 10, 0, 0),
    )
    item = json.loads((out / "events.json").read_text(encoding="utf-8"))[0]
    assert item["date_precision"] == "MONTH"
    assert item["window_start"] == "2026-12-01"
    assert item["window_end"] == "2026-12-31"


def test_exact_date_defaults_to_single_day_window():
    event = normalize_event(_raw(event_date=date(2026, 11, 20)), now=datetime(2026, 11, 3, 10, 0, 0))

    assert event.date_precision == "EXACT_DATE"
    assert event.window_start == date(2026, 11, 20)
    assert event.window_end == date(2026, 11, 20)
