"""Trading day and event session date alignment."""

from __future__ import annotations
from datetime import date
from typing import Sequence


def resolve_event_session(
    event_date: date,
    time_context: str,
    trading_days: Sequence[date],
) -> tuple[date, str]:
    """Align event date and time context to trading session date (D0).

    Returns:
    (event_session_date, confidence)
    where confidence is "HIGH" or "LOW".
    """
    sorted_days = sorted(trading_days)
    time_context = time_context.strip().upper()

    if time_context == "AFTERHOURS":
        # Strictly the next trading day
        future_days = [d for d in sorted_days if d > event_date]
        if future_days:
            return future_days[0], "HIGH"
        return event_date, "LOW"

    if time_context in ("PREMARKET", "INTRADAY"):
        if event_date in sorted_days:
            return event_date, "HIGH"
        # Non-trading day: move to next trading day with LOW confidence
        future_days = [d for d in sorted_days if d > event_date]
        if future_days:
            return future_days[0], "LOW"
        return event_date, "LOW"

    # DATE_ONLY fallback
    if event_date in sorted_days:
        return event_date, "HIGH"

    future_days = [d for d in sorted_days if d > event_date]
    if future_days:
        return future_days[0], "LOW"
    return event_date, "LOW"
