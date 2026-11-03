import json
from datetime import date, datetime

import pandas as pd

from event_radar.export import export_site_data
from event_radar.models import Event, RawEvent
from event_radar.pipeline import PipelineConfig, run_pipeline


def _canonical_unmapped_event() -> Event:
    now = datetime(2026, 11, 3, 9, 0)
    return Event(
        event_id="theme-unmapped-1",
        country="KR",
        event_type="TENDER",
        event_name="체코 원전 우선협상대상자 선정",
        primary_ticker="",
        primary_company="체코 원전",
        announced_at=now,
        event_date=date(2026, 12, 18),
        status="EXPECTED",
        source_kind="SECONDARY",
        source_name="NEWS_FUTURE",
        source_url="https://example.com/czech-nuclear",
        first_seen_at=now,
        last_seen_at=now,
    )


def test_export_marks_unmapped_event_without_fake_a_grade(tmp_path):
    event = _canonical_unmapped_event()
    output_dir = tmp_path / "site-data"

    export_site_data(
        events=[event],
        revisions=[],
        event_securities={event.event_id: []},
        event_scores={},
        event_returns_df=pd.DataFrame(),
        strategy_results={},
        backtest_summaries={},
        output_dir=output_dir,
        now=datetime(2026, 11, 3, 10, 0),
    )

    rows = json.loads((output_dir / "events.json").read_text(encoding="utf-8"))
    assert rows[0]["ticker"] == ""
    assert rows[0]["relation_grade"] == "UNMAPPED"
    assert rows[0]["relation_score"] == 0


class UnmappedThemeCollector:
    source_name = "NEWS_FUTURE"

    def collect(self, since: datetime) -> list[RawEvent]:
        return [
            RawEvent(
                source_name=self.source_name,
                source_kind="SECONDARY",
                source_event_uid="theme-unmapped-pipeline-1",
                source_url="https://example.com/control-dispute",
                country="KR",
                primary_ticker="",
                primary_company="한미약품 경영권 분쟁",
                event_type="CONTROL_DISPUTE",
                event_name="한미약품 경영권 분쟁 임시주총",
                announced_at=datetime(2026, 11, 3, 9, 0),
                event_date=date(2026, 12, 18),
                status="EXPECTED",
            )
        ]


def test_pipeline_keeps_unmapped_future_event_without_crashing(tmp_path):
    cfg = PipelineConfig(
        data_dir=tmp_path / "data",
        site_dir=tmp_path / "site",
        config_dir=tmp_path / "config",
    )

    report = run_pipeline(
        collectors=[UnmappedThemeCollector()],
        config=cfg,
        now=datetime(2026, 11, 3, 10, 0),
        skip_price_fetch=True,
    )

    assert report.success is True
    rows = json.loads((cfg.site_dir / "data" / "events.json").read_text(encoding="utf-8"))
    assert rows[0]["relation_grade"] == "UNMAPPED"
    assert rows[0]["relation_score"] == 0
