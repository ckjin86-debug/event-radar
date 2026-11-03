from datetime import date, datetime

from event_radar.export import _serialize_securities
from event_radar.models import Event, Relation
from event_radar.relations import resolve_related_securities


def test_verified_manual_relation_preserves_provenance_for_site_json():
    event = Event(
        event_id="KR_TEST_1",
        country="KR",
        event_type="CAPEX",
        event_name="테스트 데이터센터 투자",
        primary_ticker="",
        primary_company="현대차그룹",
        announced_at=datetime(2026, 11, 3, 9, 0),
        event_date=date(2027, 3, 1),
        source_name="NEWS_FUTURE",
        first_seen_at=datetime(2026, 11, 3, 9, 0),
        last_seen_at=datetime(2026, 11, 3, 9, 0),
    )
    relation = Relation(
        relation_id="MANUAL_HMG_LS",
        from_entity="현대차그룹",
        to_ticker="010120",
        relation_type="POWER_INFRA_SUPPLIER",
        relation_grade="B",
        relation_score=85,
        relation_known_date=date(2026, 11, 3),
        relation_start_date=date(2026, 11, 3),
        evidence_source="공식 IR",
        source_url="https://example.com/ir",
        ingest_mode="MANUAL",
    )

    rows = resolve_related_securities(event, [relation])
    row = next(item for item in rows if item.ticker == "010120")

    assert row.evidence_source == "공식 IR"
    assert row.source_url == "https://example.com/ir"
    assert row.relation_known_date == date(2026, 11, 3)
    assert row.ingest_mode == "MANUAL"
    assert row.from_entity == "현대차그룹"

    payload = _serialize_securities([row])[0]
    assert payload["evidence_source"] == "공식 IR"
    assert payload["source_url"] == "https://example.com/ir"
    assert payload["relation_known_date"] == "2026-11-03"
    assert payload["ingest_mode"] == "MANUAL"
    assert payload["from_entity"] == "현대차그룹"
