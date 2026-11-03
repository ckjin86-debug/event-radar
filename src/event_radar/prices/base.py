"""Price provider protocol and cached provider base."""

from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol
import pandas as pd


REQUIRED_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]


class PriceProvider(Protocol):
    """Protocol for historical market price providers."""

    def history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Fetch historical daily OHLCV prices between start and end inclusive.

        Returns DataFrame with columns:
        ['date', 'open', 'high', 'low', 'close', 'adj_close', 'volume']
        where 'date' is a date object or YYYY-MM-DD string, sorted ascending.
        """
        ...


class CachedPriceProvider:
    """Wrapper that incrementally caches price series in CSV files under cache_dir."""

    def __init__(self, delegate: PriceProvider, cache_dir: Path | str = "data/cache/prices"):
        self.delegate = delegate
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, ticker: str) -> Path:
        clean = ticker.replace("^", "_").replace(".", "_").upper()
        return self.cache_dir / f"{clean}.csv"

    @staticmethod
    def _slice(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
        if frame.empty:
            return frame
        mask = (frame["date"] >= start) & (frame["date"] <= end)
        return frame[mask].sort_values("date").reset_index(drop=True)

    def history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        cache_file = self._cache_path(ticker)
        existing_df: pd.DataFrame | None = None

        if cache_file.exists():
            try:
                existing_df = pd.read_csv(cache_file)
                existing_df["date"] = pd.to_datetime(existing_df["date"]).dt.date
                existing_df = existing_df.drop_duplicates(subset=["date"]).sort_values("date")
            except Exception:
                existing_df = None

        # No usable cache: fetch the requested range once and seed it.
        if existing_df is None or existing_df.empty:
            fresh_df = self.delegate.history(ticker, start, end)
            if fresh_df.empty:
                return fresh_df
            fresh_df = fresh_df.copy()
            fresh_df["date"] = pd.to_datetime(fresh_df["date"]).dt.date
            fresh_df = fresh_df.drop_duplicates(subset=["date"]).sort_values("date")
            fresh_df.to_csv(cache_file, index=False)
            return self._slice(fresh_df, start, end)

        min_date = existing_df["date"].min()
        max_date = existing_df["date"].max()

        # Complete cache hit.
        if min_date <= start and max_date >= end:
            return self._slice(existing_df, start, end)

        missing_ranges: list[tuple[date, date]] = []

        # If the cached block does not overlap the request at all, fetch only the
        # requested interval rather than the gap between cache and request.
        if max_date < start or min_date > end:
            missing_ranges.append((start, end))
        else:
            if start < min_date:
                missing_ranges.append((start, min(end, min_date - timedelta(days=1))))
            if end > max_date:
                missing_ranges.append((max(start, max_date + timedelta(days=1)), end))

        fresh_parts: list[pd.DataFrame] = []
        for missing_start, missing_end in missing_ranges:
            if missing_start > missing_end:
                continue
            fresh = self.delegate.history(ticker, missing_start, missing_end)
            if fresh.empty:
                continue
            fresh = fresh.copy()
            fresh["date"] = pd.to_datetime(fresh["date"]).dt.date
            fresh_parts.append(fresh)

        if fresh_parts:
            combined = pd.concat([existing_df, *fresh_parts], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date"]).sort_values("date")
            combined.to_csv(cache_file, index=False)
        else:
            combined = existing_df

        return self._slice(combined, start, end)
