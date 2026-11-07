"""Static checks for the 5% (Super Radar) tab rendering in radar-tabs.js.

The 5pct tab reproduces the original DART 5% Super Radar dashboard:
market switcher, backtest panel, KPI cards, original table columns and
a detail modal, all fed by five_pct.json fields (alpha_score etc.).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RADAR_TABS = (ROOT / "site/js/radar-tabs.js").read_text(encoding="utf-8")
APP_CSS = (ROOT / "site/css/app.css").read_text(encoding="utf-8")


def test_no_unscored_placeholder_text():
    # The old renderer hardcoded "5% 공시 · 점수 미산정" even though
    # five_pct.json carries real alpha scores.
    assert "점수 미산정" not in RADAR_TABS


def test_alpha_score_and_breakdown_are_rendered():
    assert "alpha_score" in RADAR_TABS
    assert "score_breakdown" in RADAR_TABS
    assert "sr-score-badge" in RADAR_TABS


def test_super_radar_dashboard_blocks_exist():
    for marker in (
        "switchFiveMarket",      # KR/US market switcher
        "sr-market-btn",
        "sr-backtest-panel",
        "sr-kpi-grid",
        "최고 알파 스코어 종목",
        "fiveDetailModal",       # detail modal with the factor breakdown
        "도래전",                # pending backtest pills, like the original
    ):
        assert marker in RADAR_TABS, marker


def test_us_market_empty_state_message():
    assert "미국 SEC (13D / 13G) 공시가 아직 수집되지 않았습니다" in RADAR_TABS


def test_backtest_cells_render_feed_values():
    # five_pct.json rows may carry the dual trading-day backtest
    # (five_pct_backtest); both cells must render its real values.
    for marker in (
        "ev.backtest",
        "backtest.latest",
        "backtest.firstEntry",
        "cumReturn",
        "maxRunup",
        "fiveBtPill",
    ):
        assert marker in RADAR_TABS, marker


def test_super_radar_styles_defined():
    for selector in (".sr-score-badge", ".sr-market-btn", ".sr-kpi-card",
                     ".sr-modal-backdrop", ".sr-tag-streak", ".sr-fresh-hot"):
        assert selector in APP_CSS, selector
