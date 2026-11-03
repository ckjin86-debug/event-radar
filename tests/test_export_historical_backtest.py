import json
from datetime import date, datetime

import pandas as pd

from event_radar.export import export_site_data
from event_radar.models import Event, EventSecurity


def _event(event_id: str, when: date) -> Event:
    now = datetime(2026, 11, 3, 9, 0)
    return Event(
        event_id=event_id,
        country="KR",
        event_type="TENDER",
        event_name=event_id,
        primary_ticker="005930",
        primary_company="원전 이벤트",
        announced_at=now,
        event_date=when,
        status="CONFIRMED",
        source_kind="SECONDARY",
        source_name="TEST",
        first_seen_at=now,
        last_seen_at=now,
    )


def _return_rows(event_id: str, d5: float) -> list[dict]:
    return [
        {
            "event_id": event_id,
            "ticker": "005930",
            "relation_grade": "A",
            "event_session_date": "2025-01-01",
            "offset": offset,
            "price": 100.0,
            "return_from_d0": value,
            "benchmark_return": 0.0,
            "abnormal_return": value,
            "volume_ratio_20d": 1.0,
        }
        for offset, value in [(-5, -0.01), (0, 0.0), (5, d5)]
    ]


def test_export_uses_prior_same_type_events_for_backtest(tmp_path):
    events = [
        _event("old-1", date(2024, 1, 10)),
        _event("old-2", date(2025, 4, 20)),
        _event("target", date(2026, 12, 18)),
    ]
    securities = {
        event.event_id: [
            EventSecurity(
                event_id=event.event_id,
                ticker="005930",
                relation_grade="A",
                relation_score=100,
                relation_type="DIRECT",
            )
        ]
        for event in events
    }
    returns_df = pd.DataFrame(_return_rows("old-1", 0.10) + _return_rows("old-2", -0.02))

    export_site_data(
        events=events,
        revisions=[],
        event_securities=securities,
        event_scores={},
        event_returns_df=returns_df,
        strategy_results={},
        backtest_summaries={},
        output_dir=tmp_path,
        now=datetime(2026, 11, 3, 10, 0),
    )

    details = json.loads((tmp_path / "event_details.json").read_text(encoding="utf-8"))
    target = details["target"]
    assert target["backtest_basis"] == "HISTORICAL_PEERS"
    assert target["backtest_summary"]["sample_n"] == 2
    assert target["backtest_summary"]["mean_return"] == 0.04
    assert target["event_curve"]
