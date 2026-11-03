import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "collect.py"
SPEC = importlib.util.spec_from_file_location("collect_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
collect_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collect_script)


def test_build_collectors_uses_live_core_and_v2_sources(tmp_path):
    assert hasattr(collect_script, "build_collectors")

    collectors = collect_script.build_collectors(tmp_path)
    by_name = {collector.source_name: collector for collector in collectors}

    assert by_name["DART"].fixture_path is None
    assert by_name["SEC"].fixture_path is None
    assert "HISTORICAL_SEED" in by_name
    assert "NEWS_FUTURE" in by_name
    assert "FDA_ADVISORY" in by_name
    assert "KIND_IPO" in by_name
    assert "FED_FOMC" in by_name


def test_production_news_queries_include_natural_phrasing_without_expected_word(tmp_path):
    collectors = collect_script.build_collectors(tmp_path)
    by_name = {collector.source_name: collector for collector in collectors}
    queries = set(by_name["NEWS_FUTURE"].queries)

    for query in ("신작 출시", "내달 출시", "수주 계약", "연내 인수", "경영권 분쟁"):
        assert query in queries


def test_collect_workflow_uses_optional_naver_secrets_without_sec_watchlist_or_drive_backup():
    workflow = (REPO_ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")

    assert "SEC_CIKS" not in workflow
    assert "NAVER_API_HUB_KEY_ID" in workflow
    assert "NAVER_API_HUB_KEY" in workflow
    assert "backup_drive.py" not in workflow
    assert "GOOGLE_DRIVE_FOLDER_ID" not in workflow
    assert "[skip ci]" not in workflow.lower()
