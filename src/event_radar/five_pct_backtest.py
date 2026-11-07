"""Trading-day event study for DART/SEC 5% ownership filings.

The original Chrome-extension radar measured every filing twice, on
trading days (candle indices, never calendar days):

- ① ``latest`` — returns since *this* filing's receipt date
  (``rcept_dt``): cumulative return to the latest close plus the
  D+5 / D+20 / D+60 closes after the base candle;
- ② ``firstEntry`` — the same study anchored at the reporter's
  *first-ever* 5% filing date (``first_entry_dt``), the track-record
  view, kept strictly separate from ①.

A horizon whose trading days have not elapsed yet stays ``None``
("도래전") — the original never substituted 0%. Max Run-up / MDD are
the best high / worst low inside the first 61 candles from the base
candle (the D+60 window). This module is that engine
(``computeEventStudyFromCandles``) ported to the pipeline, wired the
same way as ``five_pct_pricing``: a pipeline step enriches
``five_pct_analysis`` with ``backtest`` from the shared price provider,
and export lifts it verbatim into five_pct.json. Filings whose candles
cannot be obtained keep no ``backtest`` key at all — no estimated or
placeholder returns are ever attached.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from event_radar.five_pct_pricing import (
    _daily_candles,
    _is_five_pct_event,
    _parse_score_date,
)
from event_radar.five_pct_rules import (
    _candle_number,
    format_date_str,
    get_days_ago,
)
from event_radar.models import Event
from event_radar.prices.base import PriceProvider


# The base candle is the first candle on/after the target date, so the
# frame only needs to start a few days before the earliest anchor; the
# rest of the span (anchor → as_of) is requested in full.
_FETCH_BUFFER_DAYS = 10


def _pct1(value: float) -> float:
    """JS ``+x.toFixed(1)`` — one decimal, half-up (see five_pct_rules)."""
    return float(
        Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    )


def _normalize_study_candles(candles: Any) -> list[dict]:
    """Candle dicts → ascending rows with parsed dates, deduped by date.

    Accepts the pricing module's candle shape (``date`` as a date
    object) as well as raw dicts with string dates. Rows without a
    usable date or a positive close are dropped, mirroring the price
    frame conversion in ``five_pct_pricing._daily_candles``.
    """
    if candles is None:
        return []
    if hasattr(candles, "to_dict"):  # pandas DataFrame
        records = candles.to_dict("records")
    else:
        records = list(candles)

    rows: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        candle_date = _parse_score_date(record.get("date"))
        if candle_date is None:
            continue
        close = _candle_number(record.get("close"))
        if close is None or close <= 0:
            continue
        rows.append({
            "date": candle_date,
            "date_str": candle_date.isoformat(),
            "high": record.get("high"),
            "low": record.get("low"),
            "close": close,
        })
    rows.sort(key=lambda c: c["date"])
    deduped: list[dict] = []
    for row in rows:
        if deduped and deduped[-1]["date"] == row["date"]:
            deduped[-1] = row
        else:
            deduped.append(row)
    return deduped


def _window_metrics(
    rows: list[dict],
    target_str: str,
    reference_date: Any,
) -> Optional[dict]:
    """One anchor's event study (the original ``calcWindowMetrics``)."""
    idx = next(
        (i for i, c in enumerate(rows) if c["date_str"] >= target_str), None
    )
    if idx is None:
        return None

    base_price = rows[idx]["close"]
    if not base_price or base_price <= 0:
        return None

    avail_trading_days = (len(rows) - 1) - idx

    def pct(value: float) -> float:
        return _pct1((value - base_price) / base_price * 100)

    window = rows[idx:min(len(rows), idx + 61)]
    # JS `c.high || c.close`: a missing/zero high (low) falls back to
    # the close of the same candle.
    max_high = max((_candle_number(c["high"]) or c["close"]) for c in window)
    min_low = min((_candle_number(c["low"]) or c["close"]) for c in window)

    return {
        "baseDate": target_str,
        "marketBaseDate": rows[idx]["date_str"],
        "elapsedDays": get_days_ago(target_str, reference_date),
        "availTradingDays": avail_trading_days,
        "basePrice": base_price,
        "cumReturn": pct(rows[-1]["close"]),
        "d5": pct(rows[idx + 5]["close"]) if avail_trading_days >= 5 else None,
        "d20": pct(rows[idx + 20]["close"]) if avail_trading_days >= 20 else None,
        "d60": pct(rows[idx + 60]["close"]) if avail_trading_days >= 60 else None,
        "maxRunup": pct(max_high) if avail_trading_days >= 1 else 0.0,
        "mdd": pct(min_low) if avail_trading_days >= 1 else 0.0,
    }


def compute_event_study_from_candles(
    candles: Any,
    rcept_dt: Any,
    first_entry_dt: Any = None,
    *,
    reference_date: Any = None,
    fallback: Optional[dict] = None,
) -> Optional[dict]:
    """Dual event study for one filing — faithful port of the original
    ``computeEventStudyFromCandles(candles, rceptDt, firstHistoryDt)``.

    Returns ``{"latest": ..., "firstEntry": {..., "isSameAsLatest"}}``
    with the original's camelCase fields, or ``fallback`` when there
    are no candles or neither anchor lands on a candle. Horizons that
    have not elapsed in trading days are ``None``, never 0.
    """
    rows = _normalize_study_candles(candles)
    if not rows:
        return fallback

    first_dt = first_entry_dt or rcept_dt
    latest_metrics = _window_metrics(
        rows, format_date_str(rcept_dt), reference_date
    )
    first_metrics = _window_metrics(
        rows, format_date_str(first_dt), reference_date
    )
    if latest_metrics is None and first_metrics is None:
        return fallback

    fallback = fallback or {}
    if latest_metrics is not None:
        latest = latest_metrics
    else:
        latest = fallback.get("latest") or {
            "baseDate": format_date_str(rcept_dt),
            "elapsedDays": get_days_ago(rcept_dt, reference_date),
            "availTradingDays": 0,
            "cumReturn": 0,
            "d5": None,
            "d20": None,
            "d60": None,
            "maxRunup": None,
        }

    first_base = first_metrics or fallback.get("firstEntry") or latest_metrics
    first_entry = {
        **first_base,
        "baseDate": format_date_str(first_dt),
        "isSameAsLatest": (
            format_date_str(first_dt) == format_date_str(rcept_dt)
        ),
    }
    return {"latest": latest, "firstEntry": first_entry}


def enrich_five_pct_backtest_event(
    ev: Event,
    price_provider: PriceProvider,
    as_of: date,
    candle_cache: Optional[dict[str, Optional[list[dict]]]] = None,
) -> Event:
    """Return `ev` with ``five_pct_analysis["backtest"]`` attached.

    Falls back to the unchanged event whenever the filing has no
    analysis/ticker or no price frame is available. A caller-supplied
    ``candle_cache`` (ticker → candles or ``None``) may be shared with
    other enrichment steps, provided its frames were fetched from a
    start date covering the earliest anchor (first entry).
    """
    analysis = ev.five_pct_analysis or {}
    if not analysis:
        return ev
    ticker = (ev.primary_ticker or "").strip()
    if not ticker:
        return ev

    score_input = analysis.get("score_input")
    if not isinstance(score_input, dict):
        score_input = {}
    rcept_date = _parse_score_date(score_input.get("rcept_dt")) or ev.event_date
    first_entry_date = (
        _parse_score_date(analysis.get("first_entry_dt"))
        or _parse_score_date(score_input.get("first_entry_dt"))
        or rcept_date
    )

    candles: Optional[list[dict]] = None
    if candle_cache is not None and ticker in candle_cache:
        candles = candle_cache[ticker]
    else:
        start = (
            min(rcept_date, first_entry_date, as_of)
            - timedelta(days=_FETCH_BUFFER_DAYS)
        )
        try:
            frame = price_provider.history(ticker, start, as_of)
            candles = _daily_candles(frame, as_of)
        except Exception:
            # A price-provider failure for one filing must not stop the
            # pipeline; the filing keeps no backtest.
            candles = None
        if candle_cache is not None:
            candle_cache[ticker] = candles
    if not candles:
        return ev

    backtest = compute_event_study_from_candles(
        candles,
        rcept_date.isoformat(),
        first_entry_date.isoformat(),
        reference_date=as_of,
        fallback=analysis.get("backtest"),
    )
    if backtest is None:
        return ev

    updated = dict(analysis)
    updated["backtest"] = backtest
    return ev.model_copy(update={"five_pct_analysis": updated})


def enrich_five_pct_backtests(
    events: list[Event],
    price_provider: PriceProvider,
    as_of: date,
) -> list[Event]:
    """Backtest-enrich every five-pct event in `events` (order preserved)."""
    candle_cache: dict[str, Optional[list[dict]]] = {}
    enriched: list[Event] = []
    for ev in events:
        if _is_five_pct_event(ev) and ev.five_pct_analysis:
            enriched.append(
                enrich_five_pct_backtest_event(
                    ev, price_provider, as_of, candle_cache
                )
            )
        else:
            enriched.append(ev)
    return enriched
