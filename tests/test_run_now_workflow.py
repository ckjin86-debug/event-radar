from pathlib import Path


def test_run_now_workflow_only_auto_triggers_from_sentinel_path():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "run-now.yml").read_text(encoding="utf-8")

    assert 'paths:' in workflow
    assert 'ops/run-now.txt' in workflow
    assert 'data/' not in workflow.split('workflow_dispatch:')[0]
    assert 'python scripts/collect.py' in workflow
    assert '[skip ci]' not in workflow.lower()
