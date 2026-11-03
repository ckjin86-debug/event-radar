"""Yahoo Finance compatible price provider adapter."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests


EMPTY_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]


class YahooPriceProvider:
    """Historical price provider using Yahoo Finance's chart endpoint.

    The chart endpoint avoids the cookie/crumb flow required by the legacy CSV
    download endpoint and is therefore more reliable in unattended GitHub Actions.
    """

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

    def _parse_chart(self, payload: dict) -> pd.DataFrame:
        """Convert Yahoo chart JSON into the canonical price frame."""
        chart = payload.get("chart") or {}
        results = chart.get("result") or []
        if not results:
            return pd.DataFrame(columns=EMPTY_COLUMNS)

        result = results[0] or {}
        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quote_list = indicators.get("quote") or []
        quote = quote_list[0] if quote_list else {}
        adj_list = indicators.get("adjclose") or []
        adj = adj_list[0].get("adjclose", []) if adj_list else []

        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        rows: list[dict] = []
        for idx, ts in enumerate(timestamps):
            close = closes[idx] if idx < len(closes) else None
            if close is None:
                continue

            def value(values: list, fallback: float | int | None = close):
                item = values[idx] if idx < len(values) else None
                return fallback if item is None else item

            adj_close = value(adj, close)
            rows.append({
                "date": datetime.fromtimestamp(int(ts), tz=timezone.utc).date(),
                "open": float(value(opens, close)),
                "high": float(value(highs, close)),
                "low": float(value(lows, close)),
                "close": float(close),
                "adj_close": float(adj_close),
                "volume": int(value(volumes, 0) or 0),
            })

        if not rows:
            return pd.DataFrame(columns=EMPTY_COLUMNS)
        return pd.DataFrame(rows, columns=EMPTY_COLUMNS).sort_values("date").reset_index(drop=True)

    def history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Fetch historical price series."""
        period1 = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        period2 = int(
            datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp()
        )

        for yf_ticker in self._ticker_candidates(ticker):
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}"
                f"?period1={period1}&period2={period2}&interval=1d"
                "&events=history&includeAdjustedClose=true"
            )

            for attempt in range(self.max_retries + 1):
                try:
                    resp = self.session.get(url, timeout=self.timeout)
                    if resp.status_code == 200:
                        df = self._parse_chart(resp.json())
                        if not df.empty:
                            return df
                except Exception:
                    pass

                if attempt < self.max_retries:
                    time.sleep(0.5)

        return pd.DataFrame(columns=EMPTY_COLUMNS)
