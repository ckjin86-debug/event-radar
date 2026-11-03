"""Main scheduled collection script for Event Radar."""

import os
import sys
from pathlib import Path

# Add src to pythonpath
src_dir = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(src_dir))

from event_radar.entities import load_entity_universe
from event_radar.pipeline import run_pipeline, PipelineConfig
from event_radar.collectors.dart import DartCollector
from event_radar.collectors.sec import SecCollector
from event_radar.collectors.news_future import NewsFutureCollector
from event_radar.collectors.fda import FdaCollector
from event_radar.collectors.kind_ipo import KindIpoCollector
from event_radar.collectors.fomc import FomcCollector
from event_radar.collectors.entertainment import EntertainmentCollector
from event_radar.collectors.games import GamesCollector
from event_radar.collectors.index_changes import IndexChangesCollector


def build_collectors(root: Path):
    """Build production collectors without test fixtures."""
    return [
        DartCollector(),
        SecCollector(),
        NewsFutureCollector(),
        FdaCollector(config_path=root / "config" / "site_registry.yaml"),
        KindIpoCollector(),
        FomcCollector(),
        EntertainmentCollector(config_path=root / "config" / "site_registry.yaml"),
        GamesCollector(config_path=root / "config" / "site_registry.yaml"),
        IndexChangesCollector(config_path=root / "config" / "site_registry.yaml"),
    ]


def main():
    root = Path(__file__).resolve().parent.parent
    entity_universe = load_entity_universe(
        dart_api_key=os.getenv("DART_API_KEY", ""),
    )
    config = PipelineConfig(
        data_dir=root / "data",
        site_dir=root / "site",
        config_dir=root / "config",
        entity_universe=entity_universe,
    )

    collectors = build_collectors(root)

    print("=== Starting Event Radar Collection Pipeline ===")
    report = run_pipeline(collectors=collectors, config=config)

    print(f"Pipeline Completed in {report.duration_sec:.2f}s")
    print(f"Total events collected: {report.total_events_collected}")
    print(f"Successful sources: {', '.join(report.successful_sources)}")
    if report.failed_sources:
        print(f"Failed sources (graceful): {', '.join(report.failed_sources)}")
    print(f"New revisions recorded: {report.new_revisions_count}")


if __name__ == "__main__":
    main()
