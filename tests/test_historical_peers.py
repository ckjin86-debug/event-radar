from datetime import date, datetime

import pandas as pd

from event_radar.backtest.historical import build_historical_peer_frame
from event_radar.models import Event


def _event(event_id: str, event_date: date, event_type: str = "TENDER") -> Event:
    now = datetime(2026, 11, 3, 9, 0)
    return Event(
        event_id=event_id,
        country="KR",
        event_type=event_type,
        event_name=event_id,
        primary_ticker="005930",
        primary_company="테스트",
        announced_at=now,
        event_date=event_date,
        status="CONFIRMED",
        source_kind="SECONDARY",
        source_name="TEST",
        first_seen_at=now,
        last_seen_at=now,
    )


def _rows(event_id: str, grade: str = "A") -> list[dict]:
    return [
        {
            "event_id": event_id,
            "ticker": "005930",
            "relation_grade": grade,
            "event_session_date": "2026-01-01",
            "offset": offset,
            "price": 100 + offset,
            "return_from_d0": value,
            "benchmark_return": 0.0,
            "abnormal_return": value,
            "volume_ratio_20d": 1.0,
        }
        for offset, value in [(-5, -0.02), (0, 0.0), (5, 0.08)]
    ]


def test_historical_peers_use_only_prior_same_type_events():
    events = [
        _event("old-1", date(2024, 1, 10)),
        _event("old-2", date(2025, 4, 20)),
        _event("other-type", date(2025, 5, 1), event_type="CONTROL_DISPUTE"),
        _event("target", date(2026, 12, 18)),
        _event("future-same-type", date(2027, 1, 10)),
    ]
    returns_df = pd.DataFrame(
        _rows("old-1")
        + _rows("old-2")
        + _rows("other-type")
        + _rows("target")
        + _rows("future-same-type")
    )

    peers = build_historical_peer_frame(
        events=events,
        returns_df=returns_df,
        target_event=events[3],
        relation_grade="A",
    )

    assert set(peers["event_id"].unique()) == {"old-1", "old-2"}
    assert len(peers[peers["offset"] == 5]) == 2


def test_historical_peers_respect_relation_grade():
    events = [
        _event("old-a", date(2024, 1, 10)),
        _event("old-b", date(2025, 4, 20)),
        _event("target", date(2026, 12, 18)),
    ]
    returns_df = pd.DataFrame(_rows("old-a", "A") + _rows("old-b", "B"))

    peers = build_historical_peer_frame(
        events=events,
        returns_df=returns_df,
        target_event=events[2],
        relation_grade="B",
    )

    assert set(peers["event_id"].unique()) == {"old-b"}
