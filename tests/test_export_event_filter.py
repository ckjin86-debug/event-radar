import json
from datetime import date, datetime

from event_radar.export import export_site_data
from event_radar.models import Event


def _event(event_id: str, event_type: str) -> Event:
    now = datetime(2026, 11, 3, 10, 0, 0)
    return Event(
        event_id=event_id,
        country="KR",
        event_type=event_type,
        event_name=f"테스트 {event_type}",
        primary_ticker="123456",
        primary_company="테스트기업",
        announced_at=now,
        event_date=date(2026, 11, 20),
        event_time_context="DATE_ONLY",
        status="CONFIRMED",
        source_kind="REGULATOR",
        source_name="DART",
        source_url="https://example.com",
        source_event_uid=event_id,
        evidence_text="test",
        ingest_mode="AUTO",
        first_seen_at=now,
        last_seen_at=now,
        needs_review=False,
    )


def test_site_export_hides_generic_dart_rights_issue_but_keeps_capex(tmp_path):
    generic = _event("generic-rights", "RIGHTS_ISSUE")
    capex = _event("capex-rights", "CAPEX_FINANCING")

    export_site_data(
        events=[generic, capex],
        revisions=[],
        event_securities={},
        event_scores={},
        event_returns_df=None,
        strategy_results={},
        backtest_summaries={},
        output_dir=tmp_path,
        collector_status={},
        now=datetime(2026, 11, 3, 10, 0, 0),
    )

    events = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    details = json.loads((tmp_path / "event_details.json").read_text(encoding="utf-8"))

    assert [event["event_id"] for event in events] == ["capex-rights"]
    assert set(details) == {"capex-rights"}
