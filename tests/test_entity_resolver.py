import io
import zipfile
from datetime import date, datetime

import event_radar.entity_resolver as entity_resolver
from event_radar.models import Event
from event_radar.entity_resolver import ListedCompanyRegistry, is_market_proxy, parse_dart_corp_code_zip


def _event(name: str, company: str = "", evidence: str | None = None) -> Event:
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
        evidence_text=evidence if evidence is not None else name,
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


def test_news_direct_mapping_ignores_company_only_in_background_evidence():
    registry = ListedCompanyRegistry.from_mapping({"대우건설": "047040"})
    event = _event(
        "환경공단 기술형 입찰 발주 일정 공개",
        company="환경공단 기술형 입찰 발주 일정",
        evidence="환경공단은 12월 입찰을 진행한다. 지난해 대우건설은 다른 사업을 수주했다.",
    )

    assert registry.resolve_mentions(event) == []


def test_news_direct_mapping_keeps_company_named_in_headline():
    registry = ListedCompanyRegistry.from_mapping({"대우건설": "047040"})
    event = _event(
        "대우건설, 12월 가락우성1차 입찰 참여 예정",
        evidence="과거 수주 이력과 사업 전망도 함께 소개했다.",
    )

    rows = registry.resolve_mentions(event)
    assert [(row.ticker, row.relation_grade) for row in rows] == [("047040", "A")]


def test_registry_resolves_multiple_mentions_and_prefers_long_alias_boundary():
    registry = ListedCompanyRegistry.from_mapping(
        {
            "현대차": "005380",
            "현대차증권": "001500",
            "포스코퓨처엠": "003670",
        }
    )

    rows = registry.resolve_mentions(
        _event("현대차증권과 포스코퓨처엠이 협력하고 현대차도 투자 검토")
    )

    assert [(row.ticker, row.evidence_text) for row in rows] == [
        ("001500", "이벤트 원문에 상장사명 명시: 현대차증권"),
        ("003670", "이벤트 원문에 상장사명 명시: 포스코퓨처엠"),
        ("005380", "이벤트 원문에 상장사명 명시: 현대차"),
    ]


def test_registry_does_not_scan_one_regex_per_alias(monkeypatch):
    mapping = {f"테스트기업{index:04d}": f"{100000 + index:06d}" for index in range(500)}
    mapping["한화시스템"] = "272210"
    registry = ListedCompanyRegistry.from_mapping(mapping)

    calls = 0
    original_search = entity_resolver.re.search

    def counted_search(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_search(*args, **kwargs)

    monkeypatch.setattr(entity_resolver.re, "search", counted_search)
    rows = registry.mentioned_companies("한화시스템 11월 6일 선고")

    assert rows == [("한화시스템", "272210")]
    assert calls <= 2


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
