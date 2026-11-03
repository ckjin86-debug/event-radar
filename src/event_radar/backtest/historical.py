"""Historical peer selection for no-lookahead event-study backtests."""

from __future__ import annotations

import re

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


def build_historical_peer_frame(
    events: list[Event],
    returns_df: pd.DataFrame,
    target_event: Event,
    relation_grade: str,
) -> pd.DataFrame:
    """Return prior comparable event rows without look-ahead bias.

    Peers must be from the same country, event type/family, and relation grade,
    and must have occurred before the target event.
    """
    if returns_df.empty:
        return returns_df.copy()

    target_family = event_family_key(target_event)
    peer_ids = {
        ev.event_id
        for ev in events
        if ev.event_id != target_event.event_id
        and ev.country == target_event.country
        and ev.event_type == target_event.event_type
        and event_family_key(ev) == target_family
        and ev.event_date < target_event.event_date
    }
    if not peer_ids:
        return returns_df.iloc[0:0].copy()

    mask = returns_df["event_id"].isin(peer_ids)
    if "relation_grade" in returns_df.columns and relation_grade:
        mask &= returns_df["relation_grade"] == relation_grade
    return returns_df.loc[mask].copy()
