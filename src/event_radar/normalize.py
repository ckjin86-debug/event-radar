"""Normalization utilities converting RawEvent to canonical Event."""

from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from event_radar.models import RawEvent, Event
from event_radar.ids import make_event_id


def parse_date(val: date | datetime | str) -> date:
    """Parse date from multiple input formats."""
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    # Try YYYY-MM-DD
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return date.fromisoformat(s[:10])
    # Try YYYYMMDD
    if len(s) == 8 and s.isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    # Fallback to date.fromisoformat
    return date.fromisoformat(s)


def parse_datetime(val: date | datetime | str) -> datetime:
    """Parse datetime from multiple input formats."""
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    s = str(val).strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        d = date.fromisoformat(s)
        return datetime.combine(d, datetime.min.time())
    if len(s) == 8 and s.isdigit():
        d = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return datetime.combine(d, datetime.min.time())
    return datetime.fromisoformat(s)


def normalize_event(raw: RawEvent, now: Optional[datetime] = None) -> Event:
    """Convert RawEvent into canonical Event."""
    if now is None:
        now = datetime.now()

    event_id = make_event_id(raw)
    announced_at = parse_datetime(raw.announced_at)
    event_date = parse_date(raw.event_date)
    window_start = parse_date(raw.window_start) if raw.window_start is not None else event_date
    window_end = parse_date(raw.window_end) if raw.window_end is not None else event_date
    country = "US" if raw.country.strip().upper() == "US" else "KR"
    ticker = raw.primary_ticker.strip().upper()
    event_type = raw.event_type.strip().upper()

    return Event(
        event_id=event_id,
        country=country,
        event_type=event_type,
        event_name=raw.event_name.strip(),
        primary_ticker=ticker,
        primary_company=raw.primary_company.strip(),
        announced_at=announced_at,
        event_date=event_date,
        date_precision=raw.date_precision,
        window_start=window_start,
        window_end=window_end,
        event_time_context=raw.event_time_context,
        status=raw.status,
        source_kind=raw.source_kind,
        source_name=raw.source_name.strip(),
        source_url=raw.source_url.strip(),
        source_event_uid=str(raw.source_event_uid).strip() if raw.source_event_uid else None,
        evidence_text=raw.evidence_text.strip(),
        ingest_mode=raw.ingest_mode,
        first_seen_at=now,
        last_seen_at=now,
        needs_review=False,
    )
