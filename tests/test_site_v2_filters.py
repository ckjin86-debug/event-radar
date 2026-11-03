from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_exposes_event_sources_v2_categories():
    index_html = (REPO_ROOT / "site" / "index.html").read_text(encoding="utf-8")
    filters_js = (REPO_ROOT / "site" / "js" / "filters.js").read_text(encoding="utf-8")

    for category in ("IPO", "FOMC", "뉴스촉매", "CAPEX"):
        assert f'data-filter-value="{category}"' in index_html
        assert f'cat === "{category}"' in filters_js

    assert "미래 주가 이벤트" in index_html
