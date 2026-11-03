"""Curated historical event backfill collector.

This collector intentionally reads a small evidence-backed seed file instead of trying
to reconstruct old market events from noisy current news search results. The rows are
stable, source-cited, and deduplicated by source_event_uid.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from event_radar.models import RawEvent


class HistoricalSeedCollector:
    source_name = "HISTORICAL_SEED"

    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)

    def collect(self, since: datetime) -> list[RawEvent]:
        if not self.config_path.exists():
            return []

        rows: list[RawEvent] = []
        with self.config_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row or not row.get("source_event_uid"):
                    continue
                rows.append(
                    RawEvent(
                        source_name=self.source_name,
                        source_kind="SECONDARY",
                        source_event_uid=row["source_event_uid"].strip(),
                        source_url=(row.get("source_url") or "").strip(),
                        country=(row.get("country") or "KR").strip(),
                        primary_ticker=(row.get("primary_ticker") or "").strip(),
                        primary_company=(row.get("primary_company") or "").strip(),
                        event_type=(row.get("event_type") or "OTHER").strip(),
                        event_name=(row.get("event_name") or "").strip(),
                        announced_at=(row.get("announced_at") or row.get("event_date") or "").strip(),
                        event_date=(row.get("event_date") or "").strip(),
                        event_time_context=(row.get("event_time_context") or "DATE_ONLY").strip(),  # type: ignore[arg-type]
                        status=(row.get("status") or "CONFIRMED").strip(),  # type: ignore[arg-type]
                        evidence_text=(row.get("evidence_text") or "").strip(),
                        ingest_mode="AUTO",
                        raw_payload={"historical_seed": True},
                    )
                )
        return rows
