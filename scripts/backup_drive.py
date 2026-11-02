"""Run Google Drive backup of canonical and derived datasets."""

import os
import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(src_dir))

from event_radar.integrations.google_drive import backup_files_to_drive


def main():
    root = Path(__file__).resolve().parent.parent

    # Backup targets specified in Section 12
    targets = [
        root / "data" / "canonical" / "events.csv",
        root / "data" / "canonical" / "relations.csv",
        root / "data" / "derived" / "backtest_summary.csv",
        root / "data" / "derived" / "strategy_summary.csv",
        root / "data" / "derived" / "event_scores.csv",
        root / "data" / "logs" / "collector_runs.csv",
    ]

    print("=== Starting Google Drive Backup ===")
    report = backup_files_to_drive(targets)

    if report.success:
        print(f"SUCCESS: {report.message}")
        for f in report.uploaded_files:
            print(f"  - {f}")
    else:
        print(f"WARNING: {report.message}")
        for f in report.failed_files:
            print(f"  - Failed: {f}")


if __name__ == "__main__":
    main()
