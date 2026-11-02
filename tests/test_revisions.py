from datetime import date, datetime
import pytest
from event_radar.models import Event, EventRevision
from event_radar.revisions import detect_revisions


def test_detect_revisions_for_date_and_status():
    old_event = Event(
        event_id="KR_DART_999",
        country="KR",
        event_type="EARNINGS",
        event_name="실적발표",
        primary_ticker="005930",
        primary_company="삼성전자",
        announced_at=datetime(2026, 10, 1),
        event_date=date(2026, 10, 20),
        event_time_context="DATE_ONLY",
        status="EXPECTED",
        source_kind="REGULATOR",
        source_name="DART",
        source_url="https://dart.fss.or.kr/999",
        source_event_uid="999",
        first_seen_at=datetime(2026, 10, 1),
        last_seen_at=datetime(2026, 10, 1),
    )

    new_event = old_event.model_copy(
        update={
            "event_date": date(2026, 10, 25),
            "status": "CONFIRMED",
            "source_url": "https://dart.fss.or.kr/999_rev1",
        }
    )

    existing_revisions = [
        EventRevision(
            event_id="KR_DART_999",
            revision_no=1,
            changed_at=datetime(2026, 10, 5),
            field_name="event_name",
            old_value="잠정실적발표",
            new_value="실적발표",
            source_url="https://dart.fss.or.kr/999",
        )
    ]

    now = datetime(2026, 10, 10, 15, 0)
    revs = detect_revisions(
        old_event=old_event,
        new_event=new_event,
        existing_revisions=existing_revisions,
        now=now,
        change_reason="Official date and status confirmation",
    )

    assert len(revs) == 2
    fields = {r.field_name: r for r in revs}
    assert "event_date" in fields
    assert fields["event_date"].revision_no == 2
    assert fields["event_date"].old_value == "2026-10-20"
    assert fields["event_date"].new_value == "2026-10-25"
    assert fields["event_date"].changed_at == now

    assert "status" in fields
    assert fields["status"].revision_no == 3
    assert fields["status"].old_value == "EXPECTED"
    assert fields["status"].new_value == "CONFIRMED"
