from datetime import date, datetime
import pytest
from event_radar.models import Event, EventRevision
from event_radar.dedupe import merge_events, SOURCE_PRIORITY


def make_sample_event(
    event_id="KR_DART_123",
    event_date=date(2026, 11, 20),
    source_kind="REGULATOR",
    ingest_mode="AUTO",
    status="CONFIRMED",
    needs_review=False,
):
    return Event(
        event_id=event_id,
        country="KR",
        event_type="BONUS_ISSUE",
        event_name="삼성전자 무상증자",
        primary_ticker="005930",
        primary_company="삼성전자",
        announced_at=datetime(2026, 11, 2, 9, 0),
        event_date=event_date,
        event_time_context="DATE_ONLY",
        status=status,
        source_kind=source_kind,
        source_name="DART",
        source_url="https://dart.fss.or.kr/123",
        source_event_uid="123",
        evidence_text="무상증자 신주배정",
        ingest_mode=ingest_mode,
        first_seen_at=datetime(2026, 11, 2, 9, 0),
        last_seen_at=datetime(2026, 11, 2, 9, 0),
        needs_review=needs_review,
    )


def test_same_source_uid_date_change_creates_revision_not_new_event():
    existing = [make_sample_event(event_date=date(2026, 11, 20))]
    incoming = [make_sample_event(event_date=date(2026, 11, 25))]
    revisions = []

    res = merge_events(existing=existing, incoming=incoming, existing_revisions=revisions)

    assert len(res.events) == 1
    assert res.events[0].event_date == date(2026, 11, 25)
    assert len(res.new_revisions) == 1
    rev = res.new_revisions[0]
    assert rev.event_id == "KR_DART_123"
    assert rev.field_name == "event_date"
    assert rev.old_value == "2026-11-20"
    assert rev.new_value == "2026-11-25"
    assert rev.revision_no == 1


def test_lower_source_priority_cannot_overwrite_higher_priority():
    # Existing is REGULATOR (priority 100)
    existing = [make_sample_event(event_date=date(2026, 11, 20), source_kind="REGULATOR")]
    # Incoming is SECONDARY (priority 20) with different date
    incoming = [
        make_sample_event(
            event_date=date(2026, 11, 22),
            source_kind="SECONDARY",
        )
    ]
    revisions = []

    res = merge_events(existing=existing, incoming=incoming, existing_revisions=revisions)

    # Date should remain the higher priority date (2026-11-20)
    assert res.events[0].event_date == date(2026, 11, 20)
    assert len(res.new_revisions) == 0


def test_manual_event_not_overwritten_by_auto_and_sets_needs_review():
    existing = [
        make_sample_event(
            event_date=date(2026, 11, 20),
            ingest_mode="MANUAL",
            source_kind="SECONDARY",
        )
    ]
    incoming = [
        make_sample_event(
            event_date=date(2026, 11, 25),
            ingest_mode="AUTO",
            source_kind="REGULATOR",
        )
    ]
    revisions = []

    res = merge_events(existing=existing, incoming=incoming, existing_revisions=revisions)

    # Manual value remains protected
    assert res.events[0].event_date == date(2026, 11, 20)
    # But because higher-priority official source differed, needs_review is set
    assert res.events[0].needs_review is True
    assert len(res.new_revisions) == 0
