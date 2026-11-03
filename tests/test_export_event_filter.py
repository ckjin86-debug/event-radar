import json
from datetime import date, datetime

from event_radar.export import export_site_data
from event_radar.models import Event


def _event(
    event_id: str,
    event_type: str,
    *,
    source_name: str = "DART",
    event_name: str | None = None,
    evidence_text: str = "test",
) -> Event:
    now = datetime(2026, 11, 3, 10, 0, 0)
    return Event(
        event_id=event_id,
        country="KR",
        event_type=event_type,
        event_name=event_name or f"테스트 {event_type}",
        primary_ticker="123456",
        primary_company="테스트기업",
        announced_at=now,
        event_date=date(2026, 11, 20),
        event_time_context="DATE_ONLY",
        status="CONFIRMED",
        source_kind="REGULATOR" if source_name == "DART" else "EXCHANGE",
        source_name=source_name,
        source_url="https://example.com",
        source_event_uid=event_id,
        evidence_text=evidence_text,
        ingest_mode="AUTO",
        first_seen_at=now,
        last_seen_at=now,
        needs_review=False,
    )


def _export_ids(tmp_path, events):
    export_site_data(
        events=events,
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
    exported = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    details = json.loads((tmp_path / "event_details.json").read_text(encoding="utf-8"))
    return [event["event_id"] for event in exported], set(details)


def test_site_export_hides_generic_dart_rights_issue_but_keeps_capex(tmp_path):
    generic = _event("generic-rights", "RIGHTS_ISSUE")
    capex = _event("capex-rights", "CAPEX_FINANCING")

    ids, detail_ids = _export_ids(tmp_path, [generic, capex])

    assert ids == ["capex-rights"]
    assert detail_ids == {"capex-rights"}


def test_site_export_hides_old_kind_process_milestones_but_keeps_listing(tmp_path):
    bookbuilding = _event("ipo-book", "IPO_BOOKBUILDING_START", source_name="KIND_IPO")
    subscription = _event("ipo-sub", "IPO_SUBSCRIPTION_START", source_name="KIND_IPO")
    payment = _event("ipo-pay", "IPO_PAYMENT", source_name="KIND_IPO")
    listing = _event("ipo-list", "IPO_LISTING", source_name="KIND_IPO")

    ids, detail_ids = _export_ids(tmp_path, [bookbuilding, subscription, payment, listing])

    assert ids == ["ipo-list"]
    assert detail_ids == {"ipo-list"}


def test_site_export_hides_old_generic_convertible_rows_but_keeps_actual_new_share_listing(tmp_path):
    generic_cb = _event(
        "cb-generic",
        "CONVERTIBLE_LISTING",
        event_name="테스트기업 전환사채권발행결정",
        evidence_text="운영자금 조달을 위한 전환사채 발행",
    )
    actual_listing = _event(
        "cb-listing",
        "CONVERTIBLE_LISTING",
        event_name="테스트기업 전환사채(CB)전환청구권행사(신주상장)",
        evidence_text="전환청구권 행사, 신주상장예정일 2026-11-20",
    )

    ids, detail_ids = _export_ids(tmp_path, [generic_cb, actual_listing])

    assert ids == ["cb-listing"]
    assert detail_ids == {"cb-listing"}
