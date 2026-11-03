"""Yahoo Finance compatible price provider adapter."""

from __future__ import annotations
import io
import time
from datetime import date, datetime
import pandas as pd
import requests


EMPTY_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]


class YahooPriceProvider:
    """Historical price provider using Yahoo Finance public query API."""

    def __init__(self, timeout: int = 10, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def _ticker_candidates(self, ticker: str) -> list[str]:
        """Return Yahoo symbols to try, including KOSPI/KOSDAQ fallback."""
        ticker = ticker.strip().upper()
        if len(ticker) == 6 and ticker.isdigit():
            return [f"{ticker}.KS", f"{ticker}.KQ"]
        return [ticker]

    def _parse_history(self, text: str) -> pd.DataFrame:
        df = pd.read_csv(io.StringIO(text))
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        if "date" not in df.columns:
            return pd.DataFrame(columns=EMPTY_COLUMNS)

        df["date"] = pd.to_datetime(df["date"]).dt.date
        for col in EMPTY_COLUMNS:
            if col not in df.columns:
                df[col] = df["close"] if "close" in df.columns else 0.0
        return df[EMPTY_COLUMNS].sort_values("date").reset_index(drop=True)

    def history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Fetch historical price series."""
        period1 = int(datetime.combine(start, datetime.min.time()).timestamp())
        # add 1 day to end to make sure end date is included
        period2 = int(datetime.combine(end, datetime.max.time()).timestamp()) + 86400

        for yf_ticker in self._ticker_candidates(ticker):
            url = f"https://query1.finance.yahoo.com/v7/finance/download/{yf_ticker}?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"

            for attempt in range(self.max_retries + 1):
                try:
                    resp = self.session.get(url, timeout=self.timeout)
                    if resp.status_code == 200 and "Date" in resp.text:
                        df = self._parse_history(resp.text)
                        if not df.empty:
                            return df
                except Exception:
                    pass

                if attempt < self.max_retries:
                    time.sleep(0.5)

        # Empty fallback if offline or request fails for every candidate
        return pd.DataFrame(columns=EMPTY_COLUMNS)
