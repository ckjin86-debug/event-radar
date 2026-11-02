"""Revision tracking for event changes over time."""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from event_radar.models import Event, EventRevision


MONITORED_FIELDS = [
    "event_date",
    "status",
    "event_name",
    "event_time_context",
    "primary_company",
]


def detect_revisions(
    old_event: Event,
    new_event: Event,
    existing_revisions: list[EventRevision],
    now: Optional[datetime] = None,
    change_reason: str = "",
) -> list[EventRevision]:
    """Detect field-level changes between old_event and new_event and produce revisions."""
    if now is None:
        now = datetime.now()

    # Find highest revision_no for this event_id
    current_max_rev = 0
    for r in existing_revisions:
        if r.event_id == old_event.event_id and r.revision_no > current_max_rev:
            current_max_rev = r.revision_no

    new_revisions: list[EventRevision] = []

    for field in MONITORED_FIELDS:
        old_val = getattr(old_event, field, None)
        new_val = getattr(new_event, field, None)

        # Convert to string for consistent comparison and storage
        old_str = old_val.isoformat() if hasattr(old_val, "isoformat") else str(old_val if old_val is not None else "")
        new_str = new_val.isoformat() if hasattr(new_val, "isoformat") else str(new_val if new_val is not None else "")

        if old_str != new_str:
            current_max_rev += 1
            new_revisions.append(
                EventRevision(
                    event_id=old_event.event_id,
                    revision_no=current_max_rev,
                    changed_at=now,
                    field_name=field,
                    old_value=old_str,
                    new_value=new_str,
                    source_url=new_event.source_url or old_event.source_url,
                    change_reason=change_reason,
                )
            )

    return new_revisions
