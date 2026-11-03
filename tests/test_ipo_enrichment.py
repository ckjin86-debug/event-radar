from datetime import date, datetime

from event_radar.entity_resolver import ListedCompanyRegistry
from event_radar.ipo_enrichment import IpoRelationEnricher
from event_radar.models import Event


def _event(company: str = "테스트IPO") -> Event:
    now = datetime(2026, 11, 3, 15, 0)
    return Event(
        event_id="IPO_TEST",
        country="KR",
        event_type="IPO_LISTING",
        event_name=f"{company} 상장예정일",
        primary_ticker="",
        primary_company=company,
        announced_at=now,
        event_date=date(2026, 11, 20),
        status="CONFIRMED",
        source_kind="EXCHANGE",
        source_name="KIND_IPO",
        evidence_text=f"{company} 코스닥 상장 예정",
        first_seen_at=now,
        last_seen_at=now,
    )


def _item(title: str, description: str = "", url: str = "https://example.com/article") -> dict:
    return {
        "title": title,
        "description": description,
        "originallink": url,
        "link": url,
        "pubDate": "Mon, 02 Nov 2026 09:00:00 +0900",
    }


def test_ipo_enrichment_maps_explicit_major_shareholder_as_b():
    registry = ListedCompanyRegistry.from_mapping({"상장지주": "123456"})
    payload = {"items": [_item("테스트IPO 최대주주 상장지주, 지분 32% 보유")]} 
    enricher = IpoRelationEnricher(mock_payloads=[payload])

    rows = enricher.enrich(_event(), registry, as_of=datetime(2026, 11, 3, 15, 0))

    assert len(rows) == 1
    assert rows[0].ticker == "123456"
    assert rows[0].relation_grade == "B"
    assert rows[0].relation_type == "IPO_MAJOR_SHAREHOLDER"
    assert rows[0].relation_score >= 80


def test_ipo_enrichment_maps_disclosed_investor_as_b():
    registry = ListedCompanyRegistry.from_mapping({"벤처투자": "234567"})
    payload = {"items": [_item("벤처투자, 테스트IPO에 100억원 투자…상장 앞두고 지분가치 부각")]} 
    enricher = IpoRelationEnricher(mock_payloads=[payload])

    rows = enricher.enrich(_event(), registry, as_of=datetime(2026, 11, 3, 15, 0))

    assert len(rows) == 1
    assert rows[0].ticker == "234567"
    assert rows[0].relation_grade == "B"
    assert rows[0].relation_type == "IPO_INVESTOR"


def test_ipo_enrichment_rejects_same_industry_co_mention_without_relationship():
    registry = ListedCompanyRegistry.from_mapping({"상장로봇": "345678"})
    payload = {"items": [_item("테스트IPO·상장로봇, 로봇 업종 기대감에 동반 주목")]} 
    enricher = IpoRelationEnricher(mock_payloads=[payload])

    rows = enricher.enrich(_event(), registry, as_of=datetime(2026, 11, 3, 15, 0))

    assert rows == []


def test_ipo_enrichment_requires_ipo_company_and_related_company_in_same_clause():
    registry = ListedCompanyRegistry.from_mapping({"벤처투자": "234567"})
    payload = {
        "items": [
            _item("테스트IPO 상장 준비 본격화", "벤처투자는 다른 기업에 신규 투자를 단행했다.")
        ]
    }
    enricher = IpoRelationEnricher(mock_payloads=[payload])

    assert enricher.enrich(_event(), registry, as_of=datetime(2026, 11, 3, 15, 0)) == []


def test_ipo_enrichment_missing_credentials_is_nonfatal(monkeypatch):
    monkeypatch.delenv("NAVER_API_HUB_KEY_ID", raising=False)
    monkeypatch.delenv("NAVER_API_HUB_KEY", raising=False)
    registry = ListedCompanyRegistry.from_mapping({"상장지주": "123456"})
    enricher = IpoRelationEnricher()

    assert enricher.enrich(_event(), registry, as_of=datetime(2026, 11, 3, 15, 0)) == []
