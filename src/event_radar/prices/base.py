"""Price provider protocol and cached provider base."""

from __future__ import annotations
from datetime import date
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
    """Wrapper that caches price series in CSV files under cache_dir."""

    def __init__(self, delegate: PriceProvider, cache_dir: Path | str = "data/cache/prices"):
        self.delegate = delegate
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, ticker: str) -> Path:
        clean = ticker.replace("^", "_").replace(".", "_").upper()
        return self.cache_dir / f"{clean}.csv"

    def history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        cache_file = self._cache_path(ticker)
        existing_df: pd.DataFrame | None = None

        if cache_file.exists():
            try:
                existing_df = pd.read_csv(cache_file)
                existing_df["date"] = pd.to_datetime(existing_df["date"]).dt.date
            except Exception:
                existing_df = None

        if existing_df is not None and not existing_df.empty:
            min_date = existing_df["date"].min()
            max_date = existing_df["date"].max()
            if min_date <= start and max_date >= end:
                mask = (existing_df["date"] >= start) & (existing_df["date"] <= end)
                return existing_df[mask].sort_values("date").reset_index(drop=True)

        # Need update from delegate
        fresh_df = self.delegate.history(ticker, start, end)
        if fresh_df.empty and existing_df is not None:
            return existing_df

        if not fresh_df.empty:
            fresh_df["date"] = pd.to_datetime(fresh_df["date"]).dt.date
            if existing_df is not None and not existing_df.empty:
                combined = pd.concat([existing_df, fresh_df]).drop_duplicates(subset=["date"]).sort_values("date")
            else:
                combined = fresh_df.drop_duplicates(subset=["date"]).sort_values("date")

            combined.to_csv(cache_file, index=False)
            mask = (combined["date"] >= start) & (combined["date"] <= end)
            return combined[mask].reset_index(drop=True)

        return fresh_df
