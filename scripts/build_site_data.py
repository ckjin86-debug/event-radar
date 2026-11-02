"""Regenerate site/data/*.json static dashboard files from canonical data."""

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

    print("=== Building Public Static JSON Site Data ===")
    report = run_pipeline(collectors=[], config=config)
    print("Site data generated in site/data/")


if __name__ == "__main__":
    main()
