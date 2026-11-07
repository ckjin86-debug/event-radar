"""Pipeline-side price enrichment for DART 5% ownership filings.

The scoring core (``five_pct_rules.evaluate_signal_score``) is pure: it
applies the price-dependent half of S6 (세력 평단 안전마진) only when the
scored item carries both an average acquisition price and a current
price. At collection time neither exists, so the collector's breakdown
keeps the explicit "미산출(가격 데이터 필요)" entry.

The original Chrome-extension radar closed that gap in its enrichment
batch (``runBacktestAndPriceEnrichBatch``): fetch daily candles, set the
current price to the latest close, fill a missing average price with
the acquisition-window VWAP estimate (Priority 3 — VWAP_ESTIMATE), then
re-run the scorer on the fully priced item. This module is that wiring
for the pipeline:

- the daily frame comes from the pipeline's own price provider
  (``CachedPriceProvider(YahooPriceProvider)`` unless configured
  otherwise), the same infrastructure the backtest uses;
- the re-evaluation replays the collector's exact ``score_input`` plus
  the two prices, so every non-price factor, tag and breakdown entry is
  reproduced identically — only the S6 price entries change;
- events whose frame cannot be obtained (provider failure or empty)
  keep the collector's analysis untouched, "미산출" included. Nothing is
  estimated beyond the original's own VWAP rule, and Priority 1/2
  (DISCLOSED/DERIVED 원문 단가) remain out of scope: an average price
  already present on the item is never overwritten by the estimate.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from event_radar.five_pct_rules import (
    compute_acquisition_window_vwap,
    evaluate_signal_score,
    normalize_price_source_prefix,
)
from event_radar.models import Event
from event_radar.prices.base import PriceProvider


# The VWAP window needs at most 40 trading days before the filing candle
# (prev-filing anchor) plus the run-up to `as_of`; 200 calendar days of
# history covers both with ample buffer.
_HISTORY_LOOKBACK_DAYS = 200


def _is_five_pct_event(ev: Event) -> bool:
    return ev.event_type == "5PCT_OWNERSHIP" or ev.source_name == "DART_5PCT"


def _parse_score_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = re.sub(r"[^0-9]", "", str(value or ""))
    if len(text) == 8:
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _daily_candles(frame: Any, as_of: date) -> list[dict]:
    """Provider frame → ascending candle dicts (date objects), ≤ as_of.

    Mirrors the providers' contract (columns date/open/high/low/close/
    volume, date objects or strings). Rows without a usable date or a
    positive close are dropped; same-date rows keep the last value.
    """
    if frame is None:
        return []
    if hasattr(frame, "empty") and frame.empty:
        return []
    records = frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame)

    candles: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        candle_date = _parse_score_date(record.get("date"))
        if candle_date is None or candle_date > as_of:
            continue
        try:
            close = float(record.get("close"))
        except (TypeError, ValueError):
            continue
        if close != close or close <= 0:  # NaN or non-positive
            continue
        candles.append({
            "date": candle_date,
            "high": record.get("high"),
            "low": record.get("low"),
            "close": close,
            "volume": record.get("volume"),
        })
    candles.sort(key=lambda c: c["date"])
    deduped: list[dict] = []
    for candle in candles:
        if deduped and deduped[-1]["date"] == candle["date"]:
            deduped[-1] = candle
        else:
            deduped.append(candle)
    return deduped


def enrich_five_pct_event(
    ev: Event,
    price_provider: PriceProvider,
    as_of: date,
    candle_cache: Optional[dict[str, Optional[list[dict]]]] = None,
) -> Event:
    """Return `ev` with its five-pct analysis re-scored on real prices.

    Falls back to the unchanged event whenever the collector analysis
    has no replayable ``score_input`` or no price frame is available.
    """
    analysis = ev.five_pct_analysis or {}
    score_input = analysis.get("score_input")
    if not isinstance(score_input, dict) or not score_input:
        return ev
    ticker = (ev.primary_ticker or "").strip()
    if not ticker:
        return ev

    candles: Optional[list[dict]] = None
    if candle_cache is not None and ticker in candle_cache:
        candles = candle_cache[ticker]
    else:
        rcept_date = _parse_score_date(score_input.get("rcept_dt")) or ev.event_date
        start = min(rcept_date, as_of) - timedelta(days=_HISTORY_LOOKBACK_DAYS)
        try:
            frame = price_provider.history(ticker, start, as_of)
            candles = _daily_candles(frame, as_of)
        except Exception:
            # A price-provider failure for one filing must not stop the
            # pipeline; the filing keeps its price-free analysis.
            candles = None
        if candle_cache is not None:
            candle_cache[ticker] = candles
    if not candles:
        return ev

    # Original Step 7: current price is the latest daily close.
    current_price = candles[-1]["close"]

    item = dict(score_input)
    item["current_price"] = current_price
    if not item.get("est_avg_price"):
        # Priority 3 (VWAP_ESTIMATE): only when no DISCLOSED/DERIVED
        # average price exists, exactly as in the original.
        vwap_result = compute_acquisition_window_vwap(
            candles,
            score_input.get("rcept_dt"),
            score_input.get("prev_rcept_dt"),
            is_us=(ev.country == "US"),
        )
        if vwap_result and vwap_result["vwap"]:
            item["est_avg_price"] = vwap_result["vwap"]
            item["price_source"] = (
                f"VWAP_ESTIMATE: {vwap_result['start_date']}~{vwap_result['end_date']}"
                " 매집기간 일봉 VWAP"
            )

    result = evaluate_signal_score(item, reference_date=as_of)
    price_gap = result.get("price_gap") or {}
    investor = result.get("investor") or {}

    updated = dict(analysis)
    updated.update({
        "alpha_score": result["score"],
        "score_breakdown": result["breakdown"],
        "factor_scores": result["factor_scores"],
        "investor_class": investor.get("label"),
        "investor_type": investor.get("type"),
        "purpose_current_normalized": result.get("curr_purpose_normalized"),
        "freshness": result.get("ownership_freshness"),
        "category": result.get("category"),
        "categories": result.get("categories") or [],
        "recent_accumulation_signal_active": result.get(
            "recent_accumulation_signal_active"
        ),
        "est_avg_price": item.get("est_avg_price"),
        "current_price": current_price,
        "price_gap_pct": price_gap.get("gap_pct"),
        "price_source": price_gap.get("price_source") or (
            normalize_price_source_prefix(item.get("price_source"))
            if item.get("price_source")
            else None
        ),
    })
    return ev.model_copy(update={"five_pct_analysis": updated})


def enrich_five_pct_prices(
    events: list[Event],
    price_provider: PriceProvider,
    as_of: date,
) -> list[Event]:
    """Price-enrich every five-pct event in `events` (order preserved)."""
    candle_cache: dict[str, Optional[list[dict]]] = {}
    enriched: list[Event] = []
    for ev in events:
        if _is_five_pct_event(ev) and ev.five_pct_analysis:
            enriched.append(
                enrich_five_pct_event(ev, price_provider, as_of, candle_cache)
            )
        else:
            enriched.append(ev)
    return enriched
