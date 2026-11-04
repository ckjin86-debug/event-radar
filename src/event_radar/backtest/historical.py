"""Historical peer selection for no-lookahead event-study backtests."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from event_radar.models import Event


_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("NUCLEAR", r"원전|원자력|소형모듈원자로|\bSMR\b|nuclear"),
    ("DEFENSE", r"방산|방위|전차|미사일|군함|잠수함|무기|defen[cs]e"),
    ("SEMICONDUCTOR", r"반도체|파운드리|메모리|HBM|semiconductor"),
    ("BATTERY", r"배터리|이차전지|2차전지|battery"),
)


def event_family_key(event: Event) -> str:
    """Return a conservative family key so unrelated events are not pooled."""
    text = " ".join(
        part for part in (event.event_name, event.primary_company, event.evidence_text) if part
    )
    family = "GENERAL"
    for name, pattern in _FAMILY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            family = name
            break
    return f"{event.event_type}:{family}"


def eligible_peer_events(events: list[Event], target: Event, as_of: date | None = None) -> list[Event]:
    """Event eligibility before price joins; preserves missing-data denominators."""
    cutoff = min(target.event_date, as_of) if as_of else target.event_date
    unique: dict[tuple, Event] = {}
    for event in events:
        if (event.event_id == target.event_id or event.country != target.country
            or event.event_type != target.event_type or event_family_key(event) != event_family_key(target)
            or event.event_date >= cutoff or event.date_precision != 'EXACT_DATE'
            or event.status == 'CANCELLED' or event.needs_review):
            continue
        key = (event.country, event.event_type, event.event_date, event.primary_ticker, event.primary_company)
        unique.setdefault(key, event)
    return list(unique.values())


def build_historical_peer_frame(
    events: list[Event],
    returns_df: pd.DataFrame,
    target_event: Event,
    relation_grade: str,
    as_of: date | None = None,
) -> pd.DataFrame:
    """Return prior comparable event rows without look-ahead bias.

    Peers must be from the same country, event type/family, and relation grade,
    and must have occurred before the target event.
    """
    if returns_df.empty:
        return returns_df.copy()

    peer_ids = {event.event_id for event in eligible_peer_events(events, target_event, as_of)}
    if not peer_ids:
        return returns_df.iloc[0:0].copy()

    mask = returns_df["event_id"].isin(peer_ids)
    if "relation_grade" in returns_df.columns and relation_grade:
        mask &= returns_df["relation_grade"] == relation_grade
    frame = returns_df.loc[mask].copy()
    cutoff = min(target_event.event_date, as_of) if as_of else target_event.event_date
    if "event_session_date" in frame.columns:
        # New frames carry the actual quote date; legacy frames use business-day
        # alignment until their cached prices are rebuilt.
        sessions = pd.to_datetime(frame["event_session_date"], errors="coerce")
        if "price_date" in frame.columns:
            observed = pd.to_datetime(frame["price_date"], errors="coerce")
        else:
            observed = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
        inferred = pd.Series([session + pd.offsets.BDay(int(offset)) if pd.notna(session) else pd.NaT
                              for session, offset in zip(sessions, frame["offset"])], index=frame.index)
        observed = observed.fillna(inferred)
        frame = frame.loc[(observed < pd.Timestamp(cutoff)) & (sessions < pd.Timestamp(cutoff))]
    return frame
