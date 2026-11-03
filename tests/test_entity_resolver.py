import io
import zipfile
from datetime import date, datetime

from event_radar.models import Event
from event_radar.entity_resolver import ListedCompanyRegistry, is_market_proxy, parse_dart_corp_code_zip


def _event(name: str, company: str = "") -> Event:
    now = datetime(2026, 11, 3, 15, 0)
    return Event(
        event_id="EVT_ENTITY_TEST",
        country="KR",
        event_type="COURT_RULING",
        event_name=name,
        primary_ticker="",
        primary_company=company,
        announced_at=now,
        event_date=date(2026, 11, 6),
        status="EXPECTED",
        source_kind="SECONDARY",
        source_name="NEWS_FUTURE",
        evidence_text=name,
        first_seen_at=now,
        last_seen_at=now,
    )


def test_registry_resolves_explicit_listed_company_mentions():
    registry = ListedCompanyRegistry.from_mapping(
        {
            "한화시스템": "272210",
            "삼성바이오로직스": "207940",
        }
    )

    hanwha = registry.resolve_mentions(_event("흥국생명·한화시스템 321억 맞소송, 11월 6일 선고"))
    samsung = registry.resolve_mentions(_event("삼성바이오로직스, 연내 폴리펩타이드 사업 인수 마무리"))

    assert [(row.ticker, row.relation_grade, row.relation_type) for row in hanwha] == [
        ("272210", "A", "DIRECT_MENTION")
    ]
    assert [(row.ticker, row.relation_grade, row.relation_type) for row in samsung] == [
        ("207940", "A", "DIRECT_MENTION")
    ]


def test_registry_rejects_short_or_partial_company_names():
    registry = ListedCompanyRegistry.from_mapping({"SK": "034730", "한화시스템": "272210"})
    rows = registry.resolve_mentions(_event("한화시스템즈 신제품 출시 예정"))
    assert rows == []


def test_dart_corp_code_zip_parser_keeps_only_listed_companies():
    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <result>
      <list><corp_code>001</corp_code><corp_name>한화시스템</corp_name><stock_code>272210</stock_code></list>
      <list><corp_code>002</corp_code><corp_name>비상장회사</corp_name><stock_code></stock_code></list>
    </result>
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)

    mapping = parse_dart_corp_code_zip(buffer.getvalue())
    assert mapping == {"한화시스템": "272210"}


def test_market_proxy_classifier_is_explicit():
    for ticker in ("^KS11", "^KQ11", "^GSPC", "XBI"):
        assert is_market_proxy(ticker)
    assert not is_market_proxy("272210")
