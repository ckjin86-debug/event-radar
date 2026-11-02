"""Statistical summary metrics for backtest event groups."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd


@dataclass
class BacktestSummary:
    sample_n: int = 0
    mean_return: float = 0.0
    median_return: float = 0.0
    win_rate: float = 0.0
    standard_deviation: float = 0.0
    max_gain: float = 0.0
    max_loss: float = 0.0
    max_drawdown: float = 0.0
    mean_abnormal_return: float = 0.0
    median_abnormal_return: float = 0.0


def calculate_max_drawdown(series: pd.Series | np.ndarray) -> float:
    """Calculate maximum peak-to-trough drawdown from an array of cumulative values."""
    if len(series) == 0:
        return 0.0
    arr = np.array(series, dtype=float)
    peak = arr[0]
    max_dd = 0.0
    for val in arr:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd
    return float(max_dd)


def summarize_event_group(
    df: pd.DataFrame,
    target_offset: Optional[int] = None,
) -> BacktestSummary:
    """Summarize returns across events for a specific target offset (e.g. +5 or 0)."""
    if df.empty:
        return BacktestSummary()

    sub = df.copy()
    if target_offset is not None and "offset" in sub.columns:
        sub = sub[sub["offset"] == target_offset]

    if sub.empty:
        return BacktestSummary()

    returns = sub["return_from_d0"].astype(float)
    abnormal = sub["abnormal_return"].astype(float)
    n = len(sub)

    win_count = (abnormal > 0).sum()
    win_rate = float(win_count / n) if n > 0 else 0.0

    mdd = calculate_max_drawdown(returns.values)

    return BacktestSummary(
        sample_n=n,
        mean_return=round(float(returns.mean()), 4),
        median_return=round(float(returns.median()), 4),
        win_rate=round(win_rate, 4),
        standard_deviation=round(float(returns.std(ddof=1)) if n > 1 else 0.0, 4),
        max_gain=round(float(returns.max()), 4),
        max_loss=round(float(returns.min()), 4),
        max_drawdown=round(mdd, 4),
        mean_abnormal_return=round(float(abnormal.mean()), 4),
        median_abnormal_return=round(float(abnormal.median()), 4),
    )
