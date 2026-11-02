"""Yahoo Finance compatible price provider adapter."""

from __future__ import annotations
import io
import time
from datetime import date, datetime
import pandas as pd
import requests


class YahooPriceProvider:
    """Historical price provider using Yahoo Finance public query API."""

    def __init__(self, timeout: int = 10, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def _normalize_ticker(self, ticker: str) -> str:
        ticker = ticker.strip().upper()
        # If Korean 6-digit ticker, default to KOSPI .KS or check
        if len(ticker) == 6 and ticker.isdigit():
            return f"{ticker}.KS"
        return ticker

    def history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Fetch historical price series."""
        yf_ticker = self._normalize_ticker(ticker)
        period1 = int(datetime.combine(start, datetime.min.time()).timestamp())
        # add 1 day to end to make sure end date is included
        period2 = int(datetime.combine(end, datetime.max.time()).timestamp()) + 86400

        url = f"https://query1.finance.yahoo.com/v7/finance/download/{yf_ticker}?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"

        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 200 and "Date" in resp.text:
                    df = pd.read_csv(io.StringIO(resp.text))
                    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
                    # Rename Date -> date, Adj Close -> adj_close
                    if "adj_close**" in df.columns:
                        df = df.rename(columns={"adj_close**": "adj_close"})
                    df["date"] = pd.to_datetime(df["date"]).dt.date
                    cols = ["date", "open", "high", "low", "close", "adj_close", "volume"]
                    for c in cols:
                        if c not in df.columns:
                            df[c] = df["close"] if "close" in df.columns else 0.0
                    return df[cols].sort_values("date").reset_index(drop=True)
            except Exception:
                pass
            time.sleep(0.5)

        # Empty fallback if offline or request fails
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "adj_close", "volume"])
