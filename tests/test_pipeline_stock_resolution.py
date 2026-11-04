from datetime import date, datetime

from event_radar.entity_resolver import ListedCompanyRegistry
from event_radar.models import Event, EventSecurity
from event_radar.pipeline import resolve_event_stock_rows


def _event(
    *,
    event_id="EVT",
    event_type="COURT_RULING",
    name="흥국생명·한화시스템 321억 맞소송, 11월 6일 선고",
    company="흥국생명",
    ticker="",
    source_name="NEWS_FUTURE",
):
    now = datetime(2026, 11, 3, 15, 0)
    return Event(
        event_id=event_id,
        country="KR" if ticker != "^GSPC" else "US",
        event_type=event_type,
        event_name=name,
        primary_ticker=ticker,
        primary_company=company,
        announced_at=now,
        event_date=date(2026, 11, 6),
        status="EXPECTED",
        source_kind="SECONDARY",
        source_name=source_name,
        evidence_text=name,
        first_seen_at=now,
        last_seen_at=now,
    )


class FakeIpoEnricher:
    def enrich(self, event, registry, as_of=None):
        if event.event_type != "IPO_LISTING":
            return []
        return [
            EventSecurity(
                event_id=event.event_id,
                ticker="123456",
                relation_grade="B",
                relation_score=88,
                relation_type="IPO_MAJOR_SHAREHOLDER",
                evidence_text="상장지주가 최대주주",
            )
        ]


def test_news_company_name_becomes_direct_listed_stock():
    registry = ListedCompanyRegistry.from_mapping({"한화시스템": "272210"})
    rows = resolve_event_stock_rows(
        _event(),
        relations=[],
        theme_mappings=[],
        registry=registry,
        ipo_enricher=FakeIpoEnricher(),
        as_of=datetime(2026, 11, 3, 15, 0),
    )

    assert rows[0].ticker == "272210"
    assert rows[0].relation_grade == "A"
    assert rows[0].relation_type == "DIRECT_MENTION"


def test_ipo_related_stock_survives_as_b_without_index_proxy():
    registry = ListedCompanyRegistry.from_mapping({"상장지주": "123456"})
    event = _event(
        event_id="IPO",
        event_type="IPO_LISTING",
        name="테스트IPO 상장예정일",
        company="테스트IPO",
        ticker="",
        source_name="KIND_IPO",
    )
    rows = resolve_event_stock_rows(
        event,
        relations=[],
        theme_mappings=[],
        registry=registry,
        ipo_enricher=FakeIpoEnricher(),
        as_of=datetime(2026, 11, 3, 15, 0),
    )

    assert [(row.ticker, row.relation_grade) for row in rows] == [("123456", "B")]
    assert all(row.ticker not in {"^KS11", "^KQ11"} for row in rows)


def test_market_proxy_remains_proxy_not_direct_candidate():
    registry = ListedCompanyRegistry.from_mapping({})
    event = _event(
        event_id="FOMC",
        event_type="FOMC_DECISION",
        name="FOMC policy decision",
        company="Federal Reserve",
        ticker="^GSPC",
        source_name="FED_FOMC",
    )
    rows = resolve_event_stock_rows(
        event,
        relations=[],
        theme_mappings=[],
        registry=registry,
        ipo_enricher=FakeIpoEnricher(),
        as_of=datetime(2026, 11, 3, 15, 0),
    )

    assert len(rows) == 1
    assert rows[0].ticker == "^GSPC"
    assert rows[0].relation_grade == "PROXY"
    assert rows[0].relation_score == 0


def test_legacy_ipo_index_is_not_listed_as_the_ipo_stock():
    event = _event(event_type='IPO_LISTING', ticker='^KQ11', source_name='KIND_IPO')
    rows = resolve_event_stock_rows(event, [], [], ListedCompanyRegistry({}), FakeIpoEnricher(), datetime(2026, 11, 3))
    assert all(row.ticker != '^KQ11' for row in rows)


def test_future_lookup_can_use_current_verified_link_but_past_lookup_cannot():
    from event_radar.models import Relation
    relation = Relation(relation_id='verified', from_entity='272210', to_ticker='012450', relation_type='OWNERSHIP_LINK',
        relation_grade='B', relation_score=82, relation_known_date=date(2026,11,4), relation_start_date=date(2026,11,4),
        evidence_source='공식 지배구조', source_url='https://example.com/ir')
    registry = ListedCompanyRegistry({'한화시스템':'272210'})
    future = _event()
    rows = resolve_event_stock_rows(future, [relation], [], registry, FakeIpoEnricher(), datetime(2026,11,4))
    assert any(s.ticker == '012450' and s.relation_grade == 'B' for s in rows)
    past = future.model_copy(update={'event_date':date(2026,11,3)})
    rows = resolve_event_stock_rows(past, [relation], [], registry, FakeIpoEnricher(), datetime(2026,11,4))
    assert not any(s.ticker == '012450' for s in rows)
