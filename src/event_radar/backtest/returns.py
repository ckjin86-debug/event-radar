"""Event window return and abnormal return computation."""

from __future__ import annotations
from datetime import date
from typing import Optional
import numpy as np
import pandas as pd


WINDOW_MIN = -60
WINDOW_MAX = 20


def calculate_event_window_returns(
    event_id: str,
    ticker: str,
    relation_grade: str,
    event_session_date: date,
    stock_prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate daily return and abnormal return from D-60 to D+20 relative to D0 session date."""
    if stock_prices.empty or benchmark_prices.empty:
        return pd.DataFrame(columns=[
            "event_id", "ticker", "relation_grade", "event_session_date",
            "offset", "price", "return_from_d0", "benchmark_return",
            "abnormal_return", "volume_ratio_20d"
        ])

    stk = stock_prices.copy()
    bm = benchmark_prices.copy()

    stk["date"] = pd.to_datetime(stk["date"]).dt.date
    bm["date"] = pd.to_datetime(bm["date"]).dt.date

    stk = stk.sort_values("date").reset_index(drop=True)
    bm = bm.sort_values("date").reset_index(drop=True)

    # Locate D0 in stock prices
    exact_match = stk.index[stk["date"] == event_session_date].tolist()
    if exact_match:
        d0_idx = exact_match[0]
    else:
        return pd.DataFrame()

    d0_stock_price = float(stk.iloc[d0_idx].get("adj_close", stk.iloc[d0_idx]["close"]))
    if not np.isfinite(d0_stock_price) or d0_stock_price <= 0:
        return pd.DataFrame()

    # Benchmark D0 price
    bm_d0_matches = bm[bm["date"] == stk.iloc[d0_idx]["date"]]
    if not bm_d0_matches.empty:
        bm_d0_price = float(bm_d0_matches.iloc[0].get("adj_close", bm_d0_matches.iloc[0]["close"]))
    else:
        return pd.DataFrame()
    if not np.isfinite(bm_d0_price) or bm_d0_price <= 0:
        return pd.DataFrame()

    bm_price_map = dict(zip(
        bm["date"],
        bm.get("adj_close", bm["close"]).astype(float)
    ))

    rows = []
    for offset in range(WINDOW_MIN, WINDOW_MAX + 1):
        idx = d0_idx + offset
        if 0 <= idx < len(stk):
            row_stk = stk.iloc[idx]
            t_date = row_stk["date"]
            price = float(row_stk.get("adj_close", row_stk["close"]))

            # Stock return from D0
            ret = (price - d0_stock_price) / d0_stock_price

            # Benchmark return from D0
            bm_price = bm_price_map.get(t_date)
            if bm_price is None or not np.isfinite(bm_price) or bm_price <= 0 or not np.isfinite(price) or price <= 0:
                continue
            bm_ret = (bm_price - bm_d0_price) / bm_d0_price

            abnormal_ret = ret - bm_ret

            # Volume ratio vs preceding 20 sessions
            vol_start = max(0, idx - 20)
            preceding_vols = stk.iloc[vol_start:idx]["volume"].astype(float)
            if len(preceding_vols) > 0 and preceding_vols.mean() > 0:
                vol_ratio = float(row_stk["volume"]) / preceding_vols.mean()
            else:
                vol_ratio = 1.0

            rows.append({
                "event_id": event_id,
                "ticker": ticker,
                "relation_grade": relation_grade,
                "event_session_date": str(event_session_date),
                "price_date": str(t_date),
                "offset": offset,
                "price": round(price, 4),
                "return_from_d0": round(ret, 6),
                "benchmark_return": round(bm_ret, 6),
                "abnormal_return": round(abnormal_ret, 6),
                "volume_ratio_20d": round(vol_ratio, 4),
            })

    return pd.DataFrame(rows)
