"""Deduplication and event merging engine based on source priority and ingest mode."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from event_radar.models import Event, EventRevision
from event_radar.revisions import detect_revisions


SOURCE_PRIORITY: dict[str, int] = {
    "REGULATOR": 100,
    "EXCHANGE": 80,
    "COMPANY": 60,
    "ORGANIZER": 40,
    "SECONDARY": 20,
}


@dataclass
class MergeResult:
    events: list[Event]
    new_revisions: list[EventRevision] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)


def merge_events(
    existing: list[Event],
    incoming: list[Event],
    existing_revisions: list[EventRevision],
    now: Optional[datetime] = None,
) -> MergeResult:
    """Merge incoming events into existing events respecting source priority and manual overrides."""
    if now is None:
        now = datetime.now()

    event_map: dict[str, Event] = {e.event_id: e.model_copy() for e in existing}
    all_revisions = list(existing_revisions)
    new_revisions: list[EventRevision] = []
    conflicts: list[dict] = []

    for inc in incoming:
        if inc.event_id not in event_map:
            # Brand new event
            inc_copy = inc.model_copy(update={"first_seen_at": now, "last_seen_at": now})
            event_map[inc.event_id] = inc_copy
            continue

        curr = event_map[inc.event_id]
        curr_prio = SOURCE_PRIORITY.get(curr.source_kind, 0)
        inc_prio = SOURCE_PRIORITY.get(inc.source_kind, 0)

        # 1. Manual Protection
        if curr.ingest_mode == "MANUAL" and inc.ingest_mode == "AUTO":
            # AUTO never overwrites MANUAL
            # If higher priority official source differs, flag needs_review
            curr.last_seen_at = now
            if curr.event_date != inc.event_date or curr.status != inc.status:
                curr.needs_review = True
                conflicts.append({
                    "event_id": curr.event_id,
                    "reason": "Official source differs from manual input",
                    "manual_date": str(curr.event_date),
                    "auto_date": str(inc.event_date),
                    "source_url": inc.source_url,
                })
            continue

        # 2. Manual Override incoming
        if inc.ingest_mode in ("MANUAL", "AUTO+MANUAL"):
            revs = detect_revisions(
                old_event=curr,
                new_event=inc,
                existing_revisions=all_revisions,
                now=now,
                change_reason="Manual override/update",
            )
            new_revisions.extend(revs)
            all_revisions.extend(revs)

            # Update event
            updated = inc.model_copy(
                update={
                    "first_seen_at": curr.first_seen_at,
                    "last_seen_at": now,
                    "needs_review": False,
                }
            )
            event_map[inc.event_id] = updated
            continue

        # 3. Both are AUTO
        if inc_prio >= curr_prio:
            # Higher or equal priority
            revs = detect_revisions(
                old_event=curr,
                new_event=inc,
                existing_revisions=all_revisions,
                now=now,
                change_reason=f"Update from {inc.source_kind} ({inc.source_name})",
            )
            new_revisions.extend(revs)
            all_revisions.extend(revs)

            updated = inc.model_copy(
                update={
                    "first_seen_at": curr.first_seen_at,
                    "last_seen_at": now,
                    "needs_review": curr.needs_review,
                }
            )
            event_map[inc.event_id] = updated
        else:
            # Lower priority source cannot overwrite higher priority
            curr.last_seen_at = now

    return MergeResult(
        events=list(event_map.values()),
        new_revisions=new_revisions,
        conflicts=conflicts,
    )
