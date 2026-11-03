from datetime import date, datetime

from event_radar import pipeline as pipeline_mod
from event_radar.entity_resolver import ListedCompanyRegistry
from event_radar.models import RawEvent
from event_radar.pipeline import PipelineConfig, run_pipeline


class MockIpoCollector:
    source_name = "KIND_IPO"

    def collect(self, since: datetime):
        return [
            RawEvent(
                source_name="KIND_IPO",
                source_kind="EXCHANGE",
                source_event_uid="IPO_TEST_1",
                source_url="https://example.com/ipo",
                country="KR",
                primary_ticker="",
                primary_company="래블업",
                event_type="IPO_LISTING",
                event_name="래블업 상장예정일",
                announced_at=datetime(2026, 11, 1),
                event_date=date(2026, 11, 20),
                status="CONFIRMED",
            )
        ]


def test_pipeline_prefetches_ipo_relations_and_reports_phase_timings(tmp_path, monkeypatch):
    captured = []

    monkeypatch.setattr(
        pipeline_mod.ListedCompanyRegistry,
        "load_korean",
        staticmethod(lambda **kwargs: ListedCompanyRegistry.from_mapping({})),
    )

    def fake_prefetch(self, companies):
        captured.extend(list(companies))

    monkeypatch.setattr(pipeline_mod.IpoRelationEnricher, "prefetch", fake_prefetch)

    cfg = PipelineConfig(
        data_dir=tmp_path / "data",
        site_dir=tmp_path / "site",
        config_dir=tmp_path / "config",
    )
    report = run_pipeline(
        collectors=[MockIpoCollector()],
        config=cfg,
        now=datetime(2026, 11, 3, 10, 0),
        skip_price_fetch=True,
    )

    assert captured == ["래블업"]
    assert report.collection_duration_sec >= 0
    assert report.mapping_duration_sec >= 0
    assert report.backtest_duration_sec >= 0
    assert report.duration_sec >= (
        report.collection_duration_sec
        + report.mapping_duration_sec
        + report.backtest_duration_sec
    )
