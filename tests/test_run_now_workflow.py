from pathlib import Path


def _workflow(name: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_run_now_workflow_only_auto_triggers_from_sentinel_path():
    workflow = _workflow("run-now.yml")

    assert 'paths:' in workflow
    assert 'ops/run-now.txt' in workflow
    assert 'data/' not in workflow.split('workflow_dispatch:')[0]
    assert 'python scripts/collect.py' in workflow
    assert '[skip ci]' not in workflow.lower()


def test_collection_workflows_deploy_pages_in_same_run():
    for name in ("run-now.yml", "collect.yml"):
        workflow = _workflow(name)
        assert "actions/configure-pages@v5" in workflow
        assert "actions/upload-pages-artifact@v3" in workflow
        assert "actions/deploy-pages@v4" in workflow
        assert 'path: "site/"' in workflow
