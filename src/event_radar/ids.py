"""ID generation utilities for Event Radar."""

from __future__ import annotations
import hashlib
import uuid
from datetime import date, datetime
from event_radar.models import RawEvent


def _extract_date_str(val: datetime | date | str) -> str:
    """Extract YYYY-MM-DD string from date/datetime/string."""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, date):
        return val.isoformat()
    val_str = str(val).strip()
    return val_str[:10] if len(val_str) >= 10 else val_str


def make_event_id(raw: RawEvent) -> str:
    """Generate a stable, unique event_id that does not change when event_date changes.

    Priority:
    1. If MANUAL: MANUAL_<uuid or manual_id>
    2. If source_event_uid present: <country>_<source_name>_<source_event_uid>
    3. Fallback: <country>_<primary_ticker>_<hash(source_url + primary_ticker + event_type + announced_date)>
    """
    country = raw.country.strip().upper()
    source_name = raw.source_name.strip().upper()

    if raw.ingest_mode == "MANUAL" or source_name == "MANUAL":
        if raw.source_event_uid:
            return f"MANUAL_{raw.source_event_uid.strip().upper()}"
        # Deterministic UUID from primary fields excluding event_date
        ann_date = _extract_date_str(raw.announced_at)
        seed = f"MANUAL:{country}:{raw.primary_ticker}:{raw.event_type}:{ann_date}:{raw.event_name}"
        return f"MANUAL_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12].upper()}"

    if raw.source_event_uid:
        clean_uid = str(raw.source_event_uid).strip().replace(" ", "_")
        return f"{country}_{source_name}_{clean_uid}"

    # Fallback without source_event_uid
    ann_date = _extract_date_str(raw.announced_at)
    key_components = [
        raw.source_url.strip(),
        raw.primary_ticker.strip().upper(),
        raw.event_type.strip().upper(),
        ann_date,
    ]
    seed = "|".join(key_components)
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12].upper()
    return f"{country}_{raw.primary_ticker}_{digest}"
