"""Import and merge logic for user manual overrides via Google Sheets or manual CSVs."""

from __future__ import annotations
import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from event_radar.models import Event, Relation, EventRevision
from event_radar.dedupe import MergeResult, merge_events
from event_radar.relations import load_relations_csv


@dataclass
class ManualInput:
    events: list[Event] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)


def load_manual_events_csv(path: Path | str) -> list[Event]:
    """Load manual events from canonical manual_events.csv."""
    path = Path(path)
    if not path.exists():
        return []

    events: list[Event] = []
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row or not row.get("event_id"):
                continue
            ann_raw = row["announced_at"].strip()
            ann = datetime.fromisoformat(ann_raw) if " " in ann_raw or "T" in ann_raw else datetime.combine(date.fromisoformat(ann_raw), datetime.min.time())
            ev_date = date.fromisoformat(row["event_date"].strip()[:10])

            f_seen = datetime.fromisoformat(row.get("first_seen_at", "").strip() or ann.isoformat())
            l_seen = datetime.fromisoformat(row.get("last_seen_at", "").strip() or datetime.now().isoformat())
            needs_rev = str(row.get("needs_review", "False")).strip().lower() in ("true", "1")

            events.append(
                Event(
                    event_id=row["event_id"].strip(),
                    country=row.get("country", "KR").strip().upper(),  # type: ignore
                    event_type=row.get("event_type", "OTHER").strip().upper(),
                    event_name=row.get("event_name", "").strip(),
                    primary_ticker=row.get("primary_ticker", "").strip().upper(),
                    primary_company=row.get("primary_company", "").strip(),
                    announced_at=ann,
                    event_date=ev_date,
                    event_time_context=row.get("event_time_context", "DATE_ONLY").strip(),  # type: ignore
                    status=row.get("status", "CONFIRMED").strip().upper(),  # type: ignore
                    source_kind=row.get("source_kind", "SECONDARY").strip().upper(),  # type: ignore
                    source_name=row.get("source_name", "MANUAL").strip(),
                    source_url=row.get("source_url", "").strip(),
                    source_event_uid=row.get("source_event_uid", "").strip() or None,
                    evidence_text=row.get("evidence_text", "").strip(),
                    ingest_mode="MANUAL",
                    first_seen_at=f_seen,
                    last_seen_at=l_seen,
                    needs_review=needs_rev,
                )
            )
    return events


def load_manual_rows(events_path: Path | str, relations_path: Path | str) -> ManualInput:
    """Load both manual events and manual relations."""
    events = load_manual_events_csv(events_path)
    relations = load_relations_csv(relations_path)
    return ManualInput(events=events, relations=relations)


def apply_manual_overrides(
    auto_events: list[Event],
    manual_events: list[Event],
    revisions: list[EventRevision],
    now: Optional[datetime] = None,
) -> MergeResult:
    """Apply manual events on top of auto-collected events with strict priority."""
    return merge_events(
        existing=auto_events,
        incoming=manual_events,
        existing_revisions=revisions,
        now=now,
    )


def apply_manual_relations(
    auto_relations: list[Relation],
    manual_relations: list[Relation],
) -> list[Relation]:
    """Merge auto relations and manual relations, prioritizing manual specifications."""
    rel_map: dict[str, Relation] = {}

    for r in auto_relations:
        key = f"{r.from_entity.upper()}->{r.to_ticker.upper()}"
        rel_map[key] = r

    for r in manual_relations:
        key = f"{r.from_entity.upper()}->{r.to_ticker.upper()}"
        rel_map[key] = r  # Manual overwrites

    return list(rel_map.values())
