from datetime import datetime

from event_radar.entity_resolver import ListedCompanyRegistry
from event_radar.ipo_enrichment import IpoRelationEnricher
from event_radar.pipeline import PipelineConfig, run_pipeline


def test_fast_refresh_does_not_call_remote_registry_or_ipo_enrichment(monkeypatch, tmp_path):
    def fail_registry(*args, **kwargs):
        raise AssertionError("fast refresh must not refresh OpenDART registry")

    def fail_prefetch(*args, **kwargs):
        raise AssertionError("fast refresh must not query IPO relation news")

    monkeypatch.setattr(ListedCompanyRegistry, "load_korean", fail_registry)
    monkeypatch.setattr(IpoRelationEnricher, "prefetch", fail_prefetch)

    data_dir = tmp_path / "data"
    site_dir = tmp_path / "site"
    config_dir = tmp_path / "config"
    (data_dir / "canonical").mkdir(parents=True)
    (data_dir / "derived").mkdir(parents=True)
    (site_dir / "data").mkdir(parents=True)
    config_dir.mkdir(parents=True)

    report = run_pipeline(
        collectors=[],
        config=PipelineConfig(data_dir=data_dir, site_dir=site_dir, config_dir=config_dir),
        now=datetime(2026, 11, 3, 18, 0),
        skip_price_fetch=True,
    )

    assert report.success is True
