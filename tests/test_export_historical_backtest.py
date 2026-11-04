import json
from datetime import date, datetime

import pandas as pd

from event_radar.export import export_site_data
from event_radar.models import Event, EventSecurity


def _event(event_id: str, when: date, source_name: str = "TEST") -> Event:
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
        source_name=source_name,
        source_url=f"https://example.com/{event_id}",
        evidence_text=f"{event_id} 근거",
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


def _securities(events: list[Event]) -> dict[str, list[EventSecurity]]:
    return {
        event.event_id: [
            EventSecurity(
                event_id=event.event_id,
                ticker="005930",
                relation_grade="A",
                relation_score=100,
                relation_type="DIRECT",
                evidence_text=f"{event.event_id} 직접 관계",
            )
        ]
        for event in events
    }


def test_export_uses_prior_same_type_events_for_backtest(tmp_path):
    events = [
        _event("old-1", date(2024, 1, 10)),
        _event("old-2", date(2025, 4, 20)),
        _event("target", date(2026, 12, 18)),
    ]
    returns_df = pd.DataFrame(_return_rows("old-1", 0.10) + _return_rows("old-2", -0.02))

    export_site_data(
        events=events,
        revisions=[],
        event_securities=_securities(events),
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
    assert target["peer_sample_n"] == 2
    assert target["d5_sample_n"] == 2
    assert [peer["event_id"] for peer in target["historical_peers"]] == ["old-1", "old-2"]
    assert target["historical_peers"][0]["event_name"] == "old-1"
    assert target["historical_peers"][0]["event_date"] == "2024-01-10"
    assert target["historical_peers"][0]["source_url"] == "https://example.com/old-1"
    assert target["historical_peers"][0]["related_securities"][0]["ticker"] == "005930"


def test_historical_seed_is_hidden_from_radar_but_used_as_backtest_peer(tmp_path):
    events = [
        _event("seed-old", date(2025, 4, 20), source_name="HISTORICAL_SEED"),
        _event("target", date(2026, 12, 18)),
    ]
    returns_df = pd.DataFrame(_return_rows("seed-old", 0.07))

    export_site_data(
        events=events,
        revisions=[],
        event_securities=_securities(events),
        event_scores={},
        event_returns_df=returns_df,
        strategy_results={},
        backtest_summaries={},
        output_dir=tmp_path,
        now=datetime(2026, 11, 3, 10, 0),
    )

    dashboard = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    details = json.loads((tmp_path / "event_details.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "historical_events.json").read_text(encoding="utf-8"))

    assert [row["event_id"] for row in dashboard] == ["target"]
    assert "seed-old" not in details
    assert details["target"]["backtest_summary"]["sample_n"] == 1
    assert details["target"]["backtest_summary"]["mean_return"] == 0.07
    assert details["target"]["historical_peers"][0]["event_id"] == "seed-old"
    assert history[0]["event_id"] == "seed-old"
    assert history[0]["event_name"] == "seed-old"
    assert history[0]["event_date"] == "2025-04-20"
    assert history[0]["related_securities"][0]["relation_grade"] == "A"


def test_peer_count_can_be_positive_when_d5_summary_is_not_complete(tmp_path):
    events = [
        _event("old-partial", date(2026, 10, 28)),
        _event("target", date(2026, 11, 3)),
    ]
    returns_df = pd.DataFrame([
        {
            "event_id": "old-partial",
            "ticker": "005930",
            "relation_grade": "A",
            "event_session_date": "2026-10-28",
            "offset": offset,
            "price": 100.0,
            "return_from_d0": value,
            "benchmark_return": 0.0,
            "abnormal_return": value,
            "volume_ratio_20d": 1.0,
        }
        for offset, value in [(-5, -0.01), (0, 0.0), (3, 0.04)]
    ])

    export_site_data(
        events=events,
        revisions=[],
        event_securities=_securities(events),
        event_scores={},
        event_returns_df=returns_df,
        strategy_results={},
        backtest_summaries={},
        output_dir=tmp_path,
        now=datetime(2026, 11, 3, 10, 0),
    )

    details = json.loads((tmp_path / "event_details.json").read_text(encoding="utf-8"))
    target = details["target"]
    assert target["peer_sample_n"] == 1
    assert target["d5_sample_n"] == 0
    assert target["backtest_summary"]["sample_n"] == 0
    assert target["historical_peers"][0]["max_offset"] == 3


def test_export_exposes_eligible_missing_prices_and_per_ticker_outcomes(tmp_path):
    events = [_event('priced', date(2024, 1, 10)), _event('missing', date(2025, 4, 20)), _event('target', date(2026, 12, 18))]
    export_site_data(events, [], _securities(events), {}, pd.DataFrame(_return_rows('priced', .1)), {}, {}, output_dir=tmp_path, now=datetime(2026, 11, 3))
    d = json.loads((tmp_path/'event_details.json').read_text('utf-8'))['target']
    assert d['insight']['coverage']['eligible_events'] == 2
    assert d['insight']['coverage']['complete_events'] == 1
    assert d['insight']['coverage']['not_calculated_events'] == 1
    assert d['historical_peers'][0]['outcomes'][0]['return_d5'] == .1
    assert d['insight']['history_confidence'] == 'LIMITED'


def test_completed_official_fomc_is_history_not_future_radar(tmp_path):
    past = _event('fed-past', date(2025, 4, 20), source_name='FED_FOMC')
    past.event_type = 'FOMC_DECISION'
    export_site_data([past], [], _securities([past]), {}, None, {}, {}, output_dir=tmp_path, now=datetime(2026, 11, 3))
    assert json.loads((tmp_path/'events.json').read_text('utf-8')) == []
    assert json.loads((tmp_path/'historical_events.json').read_text('utf-8'))[0]['event_id'] == 'fed-past'
