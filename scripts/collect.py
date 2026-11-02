"""Main scheduled collection script for Event Radar."""

import sys
from pathlib import Path

# Add src to pythonpath
src_dir = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(src_dir))

from event_radar.pipeline import run_pipeline, PipelineConfig
from event_radar.collectors.dart import DartCollector
from event_radar.collectors.sec import SecCollector
from event_radar.collectors.fda import FdaCollector
from event_radar.collectors.entertainment import EntertainmentCollector
from event_radar.collectors.games import GamesCollector
from event_radar.collectors.index_changes import IndexChangesCollector


def main():
    root = Path(__file__).resolve().parent.parent
    config = PipelineConfig(
        data_dir=root / "data",
        site_dir=root / "site",
        config_dir=root / "config",
    )

    # Instantiate all collectors
    collectors = [
        DartCollector(
            fixture_path=root / "tests" / "fixtures" / "dart" / "sample_disclosures.json"
        ),
        SecCollector(
            fixture_path=root / "tests" / "fixtures" / "sec" / "sample_submissions.json"
        ),
        FdaCollector(config_path=root / "config" / "site_registry.yaml"),
        EntertainmentCollector(config_path=root / "config" / "site_registry.yaml"),
        GamesCollector(config_path=root / "config" / "site_registry.yaml"),
        IndexChangesCollector(config_path=root / "config" / "site_registry.yaml"),
    ]

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
