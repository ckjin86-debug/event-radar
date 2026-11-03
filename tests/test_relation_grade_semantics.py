from datetime import date, datetime

from event_radar.models import Event, Relation
from event_radar.relations import resolve_related_securities


def _event():
    return Event(
        event_id="EVT",
        country="KR",
        event_type="CAPEX",
        event_name="현대차그룹 데이터센터 투자",
        primary_ticker="",
        primary_company="현대차그룹",
        announced_at=datetime(2026, 11, 3, 9, 0),
        event_date=date(2026, 12, 1),
        source_name="NEWS_FUTURE",
        first_seen_at=datetime(2026, 11, 3, 9, 0),
        last_seen_at=datetime(2026, 11, 3, 9, 0),
    )


def test_verified_b_relation_is_never_promoted_to_a_only_because_score_is_high():
    rel = Relation(
        relation_id="R1",
        from_entity="현대차그룹",
        to_ticker="010120",
        relation_type="POWER_INFRA_SUPPLIER",
        relation_grade="B",
        relation_score=95,
        relation_known_date=date(2026, 10, 1),
        relation_start_date=date(2026, 10, 1),
        evidence_source="공식 계약 관계",
        source_url="https://example.com/official",
        ingest_mode="MANUAL",
    )

    rows = resolve_related_securities(_event(), [rel])
    assert len(rows) == 1
    assert rows[0].relation_grade == "B"
    assert rows[0].relation_score == 95
