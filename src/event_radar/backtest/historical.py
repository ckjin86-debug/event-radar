"""Historical peer selection for no-lookahead event-study backtests."""

from __future__ import annotations

import pandas as pd

from event_radar.models import Event


def build_historical_peer_frame(
    events: list[Event],
    returns_df: pd.DataFrame,
    target_event: Event,
    relation_grade: str,
) -> pd.DataFrame:
    """Return realized rows from prior events of the same type and relation grade.

    The target event and any later event are excluded to prevent look-ahead bias.
    """
    if returns_df.empty:
        return returns_df.copy()

    peer_ids = {
        ev.event_id
        for ev in events
        if ev.event_id != target_event.event_id
        and ev.event_type == target_event.event_type
        and ev.event_date < target_event.event_date
    }
    if not peer_ids:
        return returns_df.iloc[0:0].copy()

    mask = returns_df["event_id"].isin(peer_ids)
    if "relation_grade" in returns_df.columns and relation_grade:
        mask &= returns_df["relation_grade"] == relation_grade
    return returns_df.loc[mask].copy()
