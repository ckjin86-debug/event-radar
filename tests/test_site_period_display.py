from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_and_detail_use_date_precision_for_period_events():
    app_js = (REPO_ROOT / "site" / "js" / "app.js").read_text(encoding="utf-8")
    detail_js = (REPO_ROOT / "site" / "js" / "event-detail.js").read_text(encoding="utf-8")

    assert "formatEventDate" in app_js
    assert "date_precision" in app_js
    assert "window_start" in app_js
    assert "window_end" in app_js

    assert "formatEventDate" in detail_js
    assert "date_precision" in detail_js
    assert "window_start" in detail_js
    assert "window_end" in detail_js
