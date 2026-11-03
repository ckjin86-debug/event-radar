import importlib
import importlib.util
from datetime import date, datetime


def _news_module():
    spec = importlib.util.find_spec("event_radar.collectors.news_future")
    assert spec is not None, "News Future collector module must exist"
    return importlib.import_module("event_radar.collectors.news_future")


def _item(title: str, description: str = "", url: str = "https://example.com/1") -> dict:
    return {
        "title": title,
        "description": description,
        "originallink": url,
        "link": url,
        "pubDate": "Tue, 03 Nov 2026 09:00:00 +0900",
    }


def test_parse_next_month_window_rolls_year():
    mod = _news_module()
    window = mod.parse_future_window("회사는 내달 신규 공장을 가동할 예정이다", date(2026, 12, 15))
    assert window is not None
    assert window.precision == "MONTH"
    assert window.start == date(2027, 1, 1)
    assert window.end == date(2027, 1, 31)


def test_parse_explicit_month_day_is_exact_date():
    mod = _news_module()
    window = mod.parse_future_window("11월 18일 신제품을 출시한다", date(2026, 11, 3))
    assert window is not None
    assert window.precision == "EXACT_DATE"
    assert window.start == date(2026, 11, 18)
    assert window.end == date(2026, 11, 18)


def test_parse_next_month_day_is_exact_date():
    mod = _news_module()
    window = mod.parse_future_window("내달 6일 선고 예정", date(2026, 11, 3))
    assert window is not None
    assert window.precision == "EXACT_DATE"
    assert window.start == date(2026, 12, 6)
    assert window.end == date(2026, 12, 6)


def test_parse_this_month_day_is_exact_date():
    mod = _news_module()
    window = mod.parse_future_window("이달 9일 매각 공고 예정", date(2026, 11, 3))
    assert window is not None
    assert window.precision == "EXACT_DATE"
    assert window.start == date(2026, 11, 9)
    assert window.end == date(2026, 11, 9)


def test_parse_next_year_quarter():
    mod = _news_module()
    window = mod.parse_future_window("내년 1분기 공장 상업가동 예정", date(2026, 11, 3))
    assert window is not None
    assert window.precision == "QUARTER"
    assert window.start == date(2027, 1, 1)
    assert window.end == date(2027, 3, 31)


def test_classify_rejects_generic_rights_issue_but_keeps_capex_issue():
    mod = _news_module()
    assert mod.classify_catalyst("회사는 내달 유상증자를 추진한다") is None
    assert mod.classify_catalyst("회사는 내달 공장 증설 시설투자 목적 유상증자를 추진한다") == "CAPEX_FINANCING"


def test_classify_requires_market_catalyst():
    mod = _news_module()
    assert mod.classify_catalyst("회사는 내달 창립기념 행사를 연다") is None
    assert mod.classify_catalyst("회사는 내달 신규 공장을 가동한다") == "PLANT_OPERATION"


def test_classify_rejects_listing_because_kind_is_authoritative():
    mod = _news_module()
    assert mod.classify_catalyst("넥스아이, 11월 12일 코스닥 상장 예정") is None


def test_classify_rejects_warrant_sale_as_m_and_a():
    mod = _news_module()
    assert mod.classify_catalyst("뷰노 유증 두 차례 연기…대표 인수권 매각 12월로") is None
    assert mod.classify_catalyst("삼성바이오로직스, 연내 바이오기업 인수 마무리") == "M_AND_A"


def test_classify_rejects_promotion_only_launch_but_keeps_meaningful_launch():
    mod = _news_module()
    assert mod.classify_catalyst("스타벅스, 다음달 토이스토리 굿즈 출시 기념 할인 프로모션") is None
    assert mod.classify_catalyst("삼성SDS, 11월 18일 신규 AI 플랫폼 정식 출시") == "PRODUCT_LAUNCH"


def test_default_queries_cover_broad_future_catalysts():
    mod = _news_module()
    assert len(mod.DEFAULT_QUERIES) >= 25
    joined = " ".join(mod.DEFAULT_QUERIES)
    for keyword in ("선고", "인수", "착공", "정책", "입찰", "경영권", "대선", "임상", "승인", "가동"):
        assert keyword in joined


def test_collector_missing_credentials_is_nonfatal(monkeypatch):
    mod = _news_module()
    monkeypatch.delenv("NAVER_API_HUB_KEY_ID", raising=False)
    monkeypatch.delenv("NAVER_API_HUB_KEY", raising=False)
    collector = mod.NewsFutureCollector()
    assert collector.collect(since=datetime(2026, 11, 1)) == []


def test_collector_emits_expected_event_from_api_payload():
    mod = _news_module()
    payload = {
        "items": [
            {
                "title": "삼성전자(005930), 내달 신규 반도체 라인 가동",
                "description": "생산능력 확대를 위한 신규 라인이 다음달 가동될 예정이다.",
                "originallink": "https://example.com/article/1",
                "link": "https://n.news.naver.com/article/1",
                "pubDate": "Tue, 03 Nov 2026 09:00:00 +0900",
            }
        ]
    }
    collector = mod.NewsFutureCollector(
        api_key_id="id",
        api_key="key",
        mock_payloads=[payload],
        queries=["내달 가동"],
    )
    events = collector.collect(since=datetime(2026, 11, 1))
    assert len(events) == 1
    event = events[0]
    assert event.primary_ticker == "005930"
    assert event.event_type == "PLANT_OPERATION"
    assert event.status == "EXPECTED"
    assert event.date_precision == "MONTH"
    assert event.window_start == date(2026, 12, 1)
    assert event.window_end == date(2026, 12, 31)


def test_collector_rejects_unrelated_future_date_and_catalyst():
    mod = _news_module()
    payload = {
        "items": [
            _item(
                "LG화학, 신규 공장은 이미 가동 중",
                "임직원 행사는 내달 개최할 예정이다.",
            )
        ]
    }
    collector = mod.NewsFutureCollector(api_key_id="id", api_key="key", mock_payloads=[payload])
    assert collector.collect(since=datetime(2026, 11, 1)) == []


def test_collector_keeps_description_only_future_catalyst_when_same_clause():
    mod = _news_module()
    payload = {
        "items": [
            _item(
                "LG엔솔, 분기 최대 매출 기록",
                "회사는 내년 8월 신규 공장 상업 가동을 계획하고 있다.",
            )
        ]
    }
    collector = mod.NewsFutureCollector(api_key_id="id", api_key="key", mock_payloads=[payload])
    events = collector.collect(since=datetime(2026, 11, 1))
    assert len(events) == 1
    assert events[0].event_type == "PLANT_OPERATION"
    assert events[0].date_precision == "MONTH"
    assert events[0].event_date == date(2027, 8, 1)


def test_collector_rejects_description_date_when_catalyst_is_other_clause():
    mod = _news_module()
    payload = {
        "items": [
            _item(
                "LG엔솔, 신규 공장 계획 검토",
                "신규 공장은 검토 중이다. 임직원 행사는 내년 8월 열린다.",
            )
        ]
    }
    collector = mod.NewsFutureCollector(api_key_id="id", api_key="key", mock_payloads=[payload])
    assert collector.collect(since=datetime(2026, 11, 1)) == []


def test_collector_rejects_broad_product_launch_but_keeps_broad_clinical_result():
    mod = _news_module()
    payload = {
        "items": [
            _item("게임사, 내년 1분기 신작 글로벌 정식 출시 예정", url="https://example.com/game"),
            _item("아리바이오, 내년 1분기 임상 3상 결과 발표 예정", url="https://example.com/clinical"),
        ]
    }
    collector = mod.NewsFutureCollector(api_key_id="id", api_key="key", mock_payloads=[payload])
    events = collector.collect(since=datetime(2026, 11, 1))
    assert len(events) == 1
    assert events[0].event_type == "CLINICAL_RESULT"
    assert events[0].date_precision == "QUARTER"


def test_collector_keeps_only_exact_date_product_launch():
    mod = _news_module()
    payload = {
        "items": [
            _item("엔씨, 다음달 신작 글로벌 정식 출시 예정", url="https://example.com/month-launch"),
            _item("엘리멘타, 12월 14일 신작 글로벌 정식 출시", url="https://example.com/exact-launch"),
        ]
    }
    collector = mod.NewsFutureCollector(api_key_id="id", api_key="key", mock_payloads=[payload])
    events = collector.collect(since=datetime(2026, 11, 1))
    assert len(events) == 1
    assert events[0].event_type == "PRODUCT_LAUNCH"
    assert events[0].date_precision == "EXACT_DATE"
    assert events[0].event_date == date(2026, 12, 14)


def test_collector_clusters_same_company_event_window_across_articles():
    mod = _news_module()
    payloads = [
        {
            "items": [
                _item(
                    "LG화학, 12월 15일 신규 배터리 공장 상업 가동 예정",
                    url="https://example.com/outlet-a",
                )
            ]
        },
        {
            "items": [
                _item(
                    "LG화학, 12월 15일 배터리 신공장 상업가동 계획",
                    url="https://example.com/outlet-b",
                )
            ]
        },
    ]
    collector = mod.NewsFutureCollector(api_key_id="id", api_key="key", mock_payloads=payloads)
    events = collector.collect(since=datetime(2026, 11, 1))
    assert len(events) == 1
    event = events[0]
    assert event.primary_company == "LG화학"
    assert event.event_type == "PLANT_OPERATION"
    assert event.raw_payload["cluster_article_count"] == 2
