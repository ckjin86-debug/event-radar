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


def test_run_now_uses_fast_refresh_without_price_refetch():
    workflow = _workflow("run-now.yml")
    assert "python scripts/collect.py --skip-price-fetch" in workflow


def test_collection_workflows_deploy_pages_in_same_run():
    for name in ("run-now.yml", "collect.yml"):
        workflow = _workflow(name)
        assert "actions/configure-pages@v5" in workflow
        assert "actions/upload-pages-artifact@v3" in workflow
        assert "actions/deploy-pages@v4" in workflow
        assert 'path: "site/"' in workflow


def test_collection_job_does_not_hold_pages_environment_while_collecting():
    for name in ("run-now.yml", "collect.yml"):
        workflow = _workflow(name)
        assert "collect-and-update:" in workflow
        assert "deploy-pages:" in workflow
        collect_block = workflow.split("collect-and-update:", 1)[1].split("deploy-pages:", 1)[0]
        deploy_block = workflow.split("deploy-pages:", 1)[1]
        assert "environment:" not in collect_block
        assert "needs: collect-and-update" in deploy_block
        assert "environment:" in deploy_block
        assert "name: github-pages" in deploy_block
        assert "actions/deploy-pages@v4" in deploy_block


def test_scheduled_and_manual_collection_share_latest_run_concurrency_group():
    for name in ("run-now.yml", "collect.yml"):
        workflow = _workflow(name)
        assert "concurrency:" in workflow
        assert "group: event-radar-collection" in workflow
        assert "cancel-in-progress: true" in workflow
