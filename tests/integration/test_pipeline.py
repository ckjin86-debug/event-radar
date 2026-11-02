from datetime import datetime, date
from pathlib import Path
import json
import pytest
from event_radar.models import RawEvent
from event_radar.pipeline import run_pipeline, PipelineConfig
from event_radar.collectors.base import Collector


class MockFailingCollector:
    source_name = "FAILING_COLLECTOR"

    def collect(self, since: datetime) -> list[RawEvent]:
        raise RuntimeError("Network down or timeout")


class MockSuccessfulCollector:
    source_name = "SUCCESS_COLLECTOR"

    def collect(self, since: datetime) -> list[RawEvent]:
        return [
            RawEvent(
                source_name="SUCCESS_COLLECTOR",
                source_kind="COMPANY",
                source_event_uid="SUCCESS_01",
                source_url="https://example.com/notice/1",
                country="KR",
                primary_ticker="005930",
                primary_company="삼성전자",
                event_type="BONUS_ISSUE",
                event_name="삼성전자 무상증자 공시",
                announced_at=datetime(2026, 11, 1),
                event_date=date(2026, 11, 20),
                status="CONFIRMED",
            )
        ]


def test_pipeline_graceful_degradation_when_collector_fails(tmp_path):
    # Setup temporary paths
    data_dir = tmp_path / "data"
    site_dir = tmp_path / "site"
    config_dir = tmp_path / "config"
    (data_dir / "canonical").mkdir(parents=True)
    (data_dir / "derived").mkdir(parents=True)
    (site_dir / "data").mkdir(parents=True)
    config_dir.mkdir(parents=True)

    cfg = PipelineConfig(
        data_dir=data_dir,
        site_dir=site_dir,
        config_dir=config_dir,
    )

    collectors: list[Collector] = [
        MockFailingCollector(),
        MockSuccessfulCollector(),
    ]

    report = run_pipeline(
        collectors=collectors,
        config=cfg,
        now=datetime(2026, 11, 2, 10, 0),
        skip_price_fetch=True,  # mock mode
    )

    assert report.success is True
    assert report.total_events_collected == 1
    assert "FAILING_COLLECTOR" in report.failed_sources
    assert "SUCCESS_COLLECTOR" in report.successful_sources

    # Check site/data/events.json was exported
    events_json = site_dir / "data" / "events.json"
    assert events_json.exists()
    data = json.loads(events_json.read_text(encoding="utf-8"))
    assert len(data) >= 1
    assert data[0]["ticker"] == "005930"
    assert data[0]["d_day"] == (date(2026, 11, 20) - date(2026, 11, 2)).days

    # Ensure no secrets in metadata or events
    meta_json = site_dir / "data" / "metadata.json"
    assert meta_json.exists()
    content = meta_json.read_text(encoding="utf-8")
    assert "secret" not in content.lower()
    assert "token" not in content.lower()
    assert "password" not in content.lower()
