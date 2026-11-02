from datetime import date, datetime
import pytest
from event_radar.models import Event, Relation
from event_radar.manual.google_sheet import (
    ManualInput,
    apply_manual_overrides,
    apply_manual_relations,
    load_manual_rows,
)


def test_load_manual_rows_from_csv(tmp_path):
    events_csv = tmp_path / "manual_events.csv"
    relations_csv = tmp_path / "manual_relations.csv"

    events_csv.write_text(
        "event_id,country,event_type,event_name,primary_ticker,primary_company,announced_at,event_date,event_time_context,status,source_kind,source_name,source_url,source_event_uid,evidence_text,ingest_mode,first_seen_at,last_seen_at,needs_review\n"
        "MANUAL_001,KR,GAME_RELEASE,크래프톤 신작 출시,259960,크래프톤,2026-11-01 00:00:00,2026-12-10,DATE_ONLY,CONFIRMED,SECONDARY,MANUAL,,MANUAL_001,지스타 발표,MANUAL,2026-11-01 00:00:00,2026-11-01 00:00:00,False\n",
        encoding="utf-8",
    )

    relations_csv.write_text(
        "relation_id,from_entity,to_ticker,relation_type,relation_grade,relation_score,relation_known_date,relation_start_date,relation_end_date,evidence_source,source_url,ingest_mode\n"
        "REL_M_01,259960,035720,PUBLISHER,B,80,2026-01-01,2026-01-01,,국내 유통 퍼블리셔 계약,,MANUAL\n",
        encoding="utf-8",
    )

    manual = load_manual_rows(events_path=events_csv, relations_path=relations_csv)
    assert len(manual.events) == 1
    assert manual.events[0].primary_ticker == "259960"
    assert manual.events[0].ingest_mode == "MANUAL"

    assert len(manual.relations) == 1
    assert manual.relations[0].to_ticker == "035720"
    assert manual.relations[0].ingest_mode == "MANUAL"


def test_manual_overrides_auto_event():
    auto_evt = Event(
        event_id="EVT_KRAFT_1",
        country="KR",
        event_type="GAME_RELEASE",
        event_name="신작 발표",
        primary_ticker="259960",
        primary_company="크래프톤",
        announced_at=datetime(2026, 11, 1),
        event_date=date(2026, 12, 1),
        status="EXPECTED",
        source_kind="SECONDARY",
        source_name="NEWS",
        ingest_mode="AUTO",
        first_seen_at=datetime(2026, 11, 1),
        last_seen_at=datetime(2026, 11, 1),
    )

    # User manually corrects date to 2026-12-10 and status to CONFIRMED
    manual_evt = auto_evt.model_copy(
        update={
            "event_date": date(2026, 12, 10),
            "status": "CONFIRMED",
            "ingest_mode": "MANUAL",
        }
    )

    res = apply_manual_overrides(auto_events=[auto_evt], manual_events=[manual_evt], revisions=[])
    assert len(res.events) == 1
    assert res.events[0].event_date == date(2026, 12, 10)
    assert res.events[0].status == "CONFIRMED"
    assert res.events[0].ingest_mode == "MANUAL"
    assert len(res.new_revisions) >= 1


def test_apply_manual_relations_overrides_auto():
    auto_rel = Relation(
        relation_id="REL_A_1",
        from_entity="259960",
        to_ticker="035720",
        relation_type="PARTNER",
        relation_grade="B",
        relation_score=65,
        relation_known_date=date(2026, 1, 1),
        relation_start_date=date(2026, 1, 1),
        ingest_mode="AUTO",
    )

    # User manual updates score to 85
    manual_rel = auto_rel.model_copy(
        update={
            "relation_score": 85,
            "relation_grade": "B",
            "ingest_mode": "MANUAL",
        }
    )

    merged = apply_manual_relations(auto_relations=[auto_rel], manual_relations=[manual_rel])
    assert len(merged) == 1
    assert merged[0].relation_score == 85
    assert merged[0].ingest_mode == "MANUAL"
