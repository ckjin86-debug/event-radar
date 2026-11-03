from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_has_visible_historical_event_library():
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "site" / "js" / "app.js").read_text(encoding="utf-8")

    assert 'id="historicalLibrary"' in html
    assert "과거 이벤트 사례" in html
    assert "data/historical_events.json" in js
    assert "related_securities" in js


def test_event_detail_separates_peer_count_from_d5_complete_count():
    html = (ROOT / "site" / "event.html").read_text(encoding="utf-8")
    js = (ROOT / "site" / "js" / "event-detail.js").read_text(encoding="utf-8")

    assert 'id="backtestVerdict"' in html
    assert 'id="historicalPeers"' in html
    assert "과거 사례 수와 D+5 완료 표본은 서로 다른 기준입니다." in html
    assert "peer_sample_n" in js
    assert "d5_sample_n" in js
    assert "D+5 완료 표본 없음" in js
    assert "historical_peers" in js
    assert "가장 좋았던 구간" in js
