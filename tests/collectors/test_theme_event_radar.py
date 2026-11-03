from datetime import datetime

from event_radar.collectors.news_future import DEFAULT_QUERIES, NewsFutureCollector, classify_catalyst


def _item(title: str, url: str = "https://example.com/theme-event") -> dict:
    return {
        "title": title,
        "description": "",
        "originallink": url,
        "link": url,
        "pubDate": "Tue, 03 Nov 2026 09:00:00 +0900",
    }


def test_market_wide_event_without_ticker_stays_unmapped():
    payload = {
        "items": [
            _item("체코 원전, 12월 18일 우선협상대상자 선정 예정")
        ]
    }
    collector = NewsFutureCollector(
        api_key_id="id",
        api_key="key",
        mock_payloads=[payload],
    )

    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 1
    assert events[0].event_type == "TENDER"
    assert events[0].primary_ticker == ""


def test_default_queries_cover_large_theme_driven_events():
    joined = " | ".join(DEFAULT_QUERIES)
    assert "경영권 분쟁" in joined
    assert "원전" in joined
    assert any(keyword in joined for keyword in ("대선", "총선", "경선"))


def test_classify_control_dispute_and_election_events():
    assert classify_catalyst("한미약품 경영권 분쟁, 12월 18일 임시주총 예정") == "CONTROL_DISPUTE"
    assert classify_catalyst("대선 경선, 12월 3일 후보 확정 예정") == "ELECTION"
