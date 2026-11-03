from datetime import date, datetime

from event_radar.export import _select_visible_events
from event_radar.models import Event, EventSecurity


def _event(event_id: str, *, source: str = "NEWS_FUTURE", event_date: date, precision: str = "EXACT_DATE", event_type: str = "CONTRACT", company: str = "테스트기업") -> Event:
    return Event(
        event_id=event_id,
        country="KR",
        event_type=event_type,
        event_name=f"{company} 미래 이벤트",
        primary_ticker="",
        primary_company=company,
        announced_at=datetime(2026, 11, 3, 9, 0),
        event_date=event_date,
        date_precision=precision,
        window_start=event_date,
        window_end=event_date if precision == "EXACT_DATE" else date(event_date.year, event_date.month, 28),
        status="EXPECTED",
        source_kind="SECONDARY",
        source_name=source,
        source_url="https://example.com",
        evidence_text="미래 일정 근거",
        ingest_mode="AUTO",
        first_seen_at=datetime(2026, 11, 3, 9, 0),
        last_seen_at=datetime(2026, 11, 3, 9, 0),
    )


def test_news_visibility_hides_vague_current_period_and_caps_feed():
    today = date(2026, 11, 3)
    vague = _event("vague", event_date=today, precision="MONTH", company="이번달 잡음")
    exact = [
        _event(f"exact-{i}", event_date=date(2026, 11, 4 + (i % 20)), company=f"기업{i}")
        for i in range(35)
    ]
    non_news = _event("fomc", source="FED_FOMC", event_date=date(2026, 12, 9), event_type="FOMC_DECISION", company="Federal Reserve")

    visible = _select_visible_events([vague, *exact, non_news], {}, today=today, max_news=30)
    ids = {event.event_id for event in visible}

    assert "vague" not in ids
    assert "fomc" in ids
    assert sum(event.source_name == "NEWS_FUTURE" for event in visible) == 30


def test_news_visibility_prioritizes_verified_relation():
    today = date(2026, 11, 3)
    mapped = _event("mapped", event_date=date(2027, 3, 1), precision="MONTH", event_type="CAPEX", company="현대차그룹")
    fillers = [
        _event(f"filler-{i}", event_date=date(2026, 12, 1), precision="MONTH", company=f"기업{i}")
        for i in range(40)
    ]
    securities = {
        "mapped": [
            EventSecurity(
                event_id="mapped",
                ticker="005380",
                relation_grade="A",
                relation_score=90,
                relation_type="PROJECT_INVESTOR",
                evidence_text="공식 투자 참여",
                ingest_mode="MANUAL",
            )
        ]
    }

    visible = _select_visible_events([mapped, *fillers], securities, today=today, max_news=30)
    assert "mapped" in {event.event_id for event in visible}
