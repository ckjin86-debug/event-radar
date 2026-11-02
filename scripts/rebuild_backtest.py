"""Rebuild backtest returns, strategy matrices, and event scores without re-collecting."""

import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(src_dir))

from event_radar.pipeline import run_pipeline, PipelineConfig


def main():
    root = Path(__file__).resolve().parent.parent
    config = PipelineConfig(
        data_dir=root / "data",
        site_dir=root / "site",
        config_dir=root / "config",
    )

    print("=== Rebuilding Backtests and Event Scores ===")
    report = run_pipeline(collectors=[], config=config)
    print(f"Rebuild completed in {report.duration_sec:.2f}s")


if __name__ == "__main__":
    main()
