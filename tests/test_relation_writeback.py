from datetime import date

import pytest

from event_radar.models import Relation
from event_radar.manual.relation_writeback import (
    RelationWritebackError,
    upsert_verified_relation,
    validate_verified_relation,
)


def _relation(**overrides):
    data = {
        "relation_id": "BBREL_TEST",
        "from_entity": "현대차그룹",
        "to_ticker": "010120",
        "relation_type": "POWER_INFRA_SUPPLIER",
        "relation_grade": "B",
        "relation_score": 82,
        "relation_known_date": date(2026, 11, 3),
        "relation_start_date": date(2026, 11, 3),
        "relation_end_date": None,
        "evidence_source": "현대차그룹 공식 보도자료와 공급사 IR 교차검증",
        "source_url": "https://example.com/official-evidence",
        "ingest_mode": "MANUAL",
    }
    data.update(overrides)
    return Relation(**data)


def test_verified_writeback_accepts_only_a_or_b_with_evidence():
    validate_verified_relation(_relation())
    validate_verified_relation(_relation(relation_grade="A", relation_score=95))

    with pytest.raises(RelationWritebackError):
        validate_verified_relation(_relation(relation_grade="C", relation_score=50))
    with pytest.raises(RelationWritebackError):
        validate_verified_relation(_relation(relation_grade="THEME", relation_score=70))
    with pytest.raises(RelationWritebackError):
        validate_verified_relation(_relation(evidence_source=""))
    with pytest.raises(RelationWritebackError):
        validate_verified_relation(_relation(source_url=""))


def test_verified_writeback_rejects_market_proxies():
    for ticker in ("^KS11", "^KQ11", "^GSPC", "XBI"):
        with pytest.raises(RelationWritebackError):
            validate_verified_relation(_relation(to_ticker=ticker))


def test_verified_writeback_enforces_score_band_for_grade():
    with pytest.raises(RelationWritebackError):
        validate_verified_relation(_relation(relation_grade="A", relation_score=89))
    with pytest.raises(RelationWritebackError):
        validate_verified_relation(_relation(relation_grade="B", relation_score=59))


def test_upsert_updates_same_entity_ticker_instead_of_duplicating():
    old = _relation(
        relation_id="BBREL_OLD",
        relation_score=72,
        evidence_source="old evidence",
        source_url="https://example.com/old",
    )
    new = _relation(
        relation_id="BBREL_NEW",
        relation_score=86,
        evidence_source="new official evidence",
        source_url="https://example.com/new",
    )

    rows, status = upsert_verified_relation([old], new)

    assert status == "UPDATED"
    assert len(rows) == 1
    assert rows[0].relation_id == "BBREL_OLD"
    assert rows[0].relation_score == 86
    assert rows[0].evidence_source == "new official evidence"
    assert rows[0].ingest_mode == "MANUAL"


def test_upsert_creates_new_manual_relation():
    rows, status = upsert_verified_relation([], _relation())
    assert status == "CREATED"
    assert len(rows) == 1
    assert rows[0].ingest_mode == "MANUAL"
