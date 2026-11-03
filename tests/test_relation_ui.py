from pathlib import Path


def _read(path: str) -> str:
    return (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")


def test_event_detail_exposes_relation_verification_groups():
    html = _read("site/event.html")
    js = _read("site/js/event-detail.js")

    assert 'id="relationSummary"' in html
    assert 'id="verifiedRelations"' in html
    assert 'id="candidateRelations"' in html
    assert 'id="referenceRelations"' in html

    assert "영구관계 등록됨" in js
    assert "자동 확인" in js
    assert "후보" in js
    assert "참고용" in js
    assert "검증 A/B" in js


def test_dashboard_shows_human_readable_mapping_status():
    js = _read("site/js/app.js")

    assert "mappingStatusText" in js
    assert "검증 관계" in js
    assert "자동 매핑" in js
    assert "테마 후보" in js
    assert "프록시" in js
    assert "미매핑" in js
