"""Collector base interface, protocol and run logger."""

from __future__ import annotations
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from event_radar.models import RawEvent


@dataclass
class CollectorRunLog:
    source_name: str
    status: str  # SUCCESS, FAILED
    items_count: int
    duration_sec: float
    error_message: str = ""
    run_at: datetime = datetime.now()


class Collector(Protocol):
    source_name: str

    def collect(self, since: datetime) -> list[RawEvent]:
        """Collect raw events since given datetime."""
        ...


def log_collector_run(run_log: CollectorRunLog, path: Path | str = "data/logs/collector_runs.csv") -> None:
    """Append collector execution log to CSV."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["source_name", "status", "items_count", "duration_sec", "error_message", "run_at"]

    write_header = not p.exists() or p.stat().st_size == 0
    with open(p, mode="a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "source_name": run_log.source_name,
            "status": run_log.status,
            "items_count": run_log.items_count,
            "duration_sec": round(run_log.duration_sec, 3),
            "error_message": run_log.error_message,
            "run_at": run_log.run_at.isoformat(),
        })
