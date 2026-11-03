import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "collect.py"
SPEC = importlib.util.spec_from_file_location("collect_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
collect_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collect_script)


def test_build_collectors_uses_live_dart_and_sec_sources(tmp_path):
    assert hasattr(collect_script, "build_collectors")

    collectors = collect_script.build_collectors(tmp_path)
    by_name = {collector.source_name: collector for collector in collectors}

    assert by_name["DART"].fixture_path is None
    assert by_name["SEC"].fixture_path is None


def test_collect_workflow_does_not_require_sec_watchlist_variable():
    workflow = (REPO_ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")
    assert "SEC_CIKS" not in workflow
