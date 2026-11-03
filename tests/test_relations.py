from datetime import date, datetime
import pytest
from event_radar.entities import SecurityMention
from event_radar.models import Event, Relation
from event_radar.relations import resolve_related_securities


def make_test_event(
    ticker="005930",
    announced_at=datetime(2026, 5, 1, 9, 0),
    event_date=date(2026, 5, 20),
):
    return Event(
        event_id="EVT_TEST_1",
        country="KR",
        event_type="BONUS_ISSUE",
        event_name="삼성전자 무상증자",
        primary_ticker=ticker,
        primary_company="삼성전자",
        announced_at=announced_at,
        event_date=event_date,
        event_time_context="DATE_ONLY",
        status="CONFIRMED",
        source_kind="REGULATOR",
        source_name="DART",
        source_url="https://dart.fss.or.kr",
        first_seen_at=announced_at,
        last_seen_at=announced_at,
    )


def test_primary_ticker_automatically_added_as_grade_a():
    event = make_test_event(ticker="005930")
    results = resolve_related_securities(event, relations=[])

    assert len(results) == 1
    assert results[0].ticker == "005930"
    assert results[0].relation_grade == "A"
    assert results[0].relation_score == 100
    assert results[0].relation_type == "DIRECT"


def test_direct_mentions_replace_market_proxy_and_keep_multiple_grade_a_issuers():
    event = make_test_event(ticker="^KS11")
    event.event_name = "흥국생명·한화시스템 321억 맞소송, 내달 6일 선고"
    event.primary_company = "흥국생명"
    mentions = [
        SecurityMention(company_name="흥국생명", ticker="000540", country="KR"),
        SecurityMention(company_name="한화시스템", ticker="272210", country="KR"),
    ]

    results = resolve_related_securities(event, relations=[], direct_mentions=mentions)
    by_ticker = {row.ticker: row for row in results}

    assert "^KS11" not in by_ticker
    assert set(by_ticker) == {"000540", "272210"}
    assert all(row.relation_grade == "A" for row in by_ticker.values())
    assert all(row.relation_type == "DIRECT_MENTION" for row in by_ticker.values())


def test_evidence_relation_can_expand_from_directly_mentioned_issuer():
    event = make_test_event(ticker="^KS11", announced_at=datetime(2026, 5, 1), event_date=date(2026, 5, 20))
    event.event_name = "한화시스템 수주 발표 예정"
    event.primary_company = "한화시스템"
    mentions = [SecurityMention(company_name="한화시스템", ticker="272210", country="KR")]
    relation = Relation(
        relation_id="REL_DIRECT_1",
        from_entity="272210",
        to_ticker="079550",
        relation_type="PARTNER",
        relation_grade="B",
        relation_score=80,
        relation_known_date=date(2026, 4, 1),
        relation_start_date=date(2026, 1, 1),
        relation_end_date=None,
        evidence_source="공시 계약서",
    )

    results = resolve_related_securities(event, relations=[relation], direct_mentions=mentions)
    by_ticker = {row.ticker: row for row in results}

    assert by_ticker["272210"].relation_grade == "A"
    assert by_ticker["079550"].relation_grade == "B"
    assert by_ticker["079550"].relation_score == 80


def test_future_known_relation_excluded_from_past_event():
    # Announced on 2026-05-01, but relation only became known on 2026-06-01
    event = make_test_event(ticker="005930", announced_at=datetime(2026, 5, 1))

    future_rel = Relation(
        relation_id="REL_1",
        from_entity="005930",
        to_ticker="000660",
        relation_type="SUPPLIER",
        relation_grade="B",
        relation_score=75,
        relation_known_date=date(2026, 6, 1),  # after announced_at!
        relation_start_date=date(2026, 1, 1),
        relation_end_date=None,
    )

    results = resolve_related_securities(event, relations=[future_rel])
    tickers = [r.ticker for r in results]
    assert "000660" not in tickers
    assert "005930" in tickers


def test_expired_relation_excluded():
    # Event is 2026-05-20, relation ended on 2026-04-30
    event = make_test_event(ticker="005930", event_date=date(2026, 5, 20))

    expired_rel = Relation(
        relation_id="REL_2",
        from_entity="005930",
        to_ticker="000660",
        relation_type="SUPPLIER",
        relation_grade="B",
        relation_score=75,
        relation_known_date=date(2026, 1, 1),
        relation_start_date=date(2026, 1, 1),
        relation_end_date=date(2026, 4, 30),  # expired!
    )

    results = resolve_related_securities(event, relations=[expired_rel])
    tickers = [r.ticker for r in results]
    assert "000660" not in tickers


def test_relation_below_60_threshold_excluded():
    event = make_test_event(ticker="005930")

    low_score_rel = Relation(
        relation_id="REL_3",
        from_entity="005930",
        to_ticker="035420",
        relation_type="THEME",
        relation_grade="C",
        relation_score=50,  # Below 60 threshold
        relation_known_date=date(2026, 1, 1),
        relation_start_date=date(2026, 1, 1),
    )

    results = resolve_related_securities(event, relations=[low_score_rel])
    tickers = [r.ticker for r in results]
    assert "035420" not in tickers


def test_valid_b_grade_relation_included():
    event = make_test_event(ticker="005930", announced_at=datetime(2026, 5, 1), event_date=date(2026, 5, 20))

    valid_b = Relation(
        relation_id="REL_4",
        from_entity="005930",
        to_ticker="000660",
        relation_type="PARTNER",
        relation_grade="B",
        relation_score=80,
        relation_known_date=date(2026, 4, 1),
        relation_start_date=date(2026, 1, 1),
        relation_end_date=date(2026, 12, 31),
        evidence_source="공시 계약서",
    )

    results = resolve_related_securities(event, relations=[valid_b])
    tickers = {r.ticker: r for r in results}
    assert "000660" in tickers
    assert tickers["000660"].relation_grade == "B"
    assert tickers["000660"].relation_score == 80
