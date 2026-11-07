"""Regenerate the SEC large-cap universe file (config/sec_large_cap_universe.json).

The SEC 8-K collector only keeps filings from large-cap companies, defined
as the union of the S&P 500 and Nasdaq-100 constituents. This script pulls
the constituent tables from Wikipedia and rewrites the JSON universe file
that `event_radar.sec_universe` loads at collection/pipeline time.

Usage:
    /tmp/er-venv/bin/python scripts/update_sec_universe.py

Index membership changes a few times a year; re-run this script and commit
the updated JSON whenever the universe should be refreshed. Tickers are
stored in SEC EDGAR style (class-share dots become dashes, e.g. BRK.B ->
BRK-B) so they compare directly against company_tickers.json values.
"""

from __future__ import annotations

import io
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "config" / "sec_large_cap_universe.json"

SOURCES = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "nasdaq100": "https://api.nasdaq.com/api/quote/list-type/nasdaq100",
}


def _tickers_from_table(url: str, column: str) -> set[str]:
    """Read one Wikipedia constituent table and return its ticker column."""
    # Wikipedia rejects the default urllib user agent with HTTP 403.
    response = requests.get(
        url,
        headers={"User-Agent": "EventRadarUniverseUpdater/1.0 (contact: admin@eventradar.org)"},
        timeout=30,
    )
    response.raise_for_status()
    for frame in pd.read_html(io.StringIO(response.text)):
        if column in frame.columns:
            return {
                str(value).strip().upper().replace(".", "-")
                for value in frame[column]
                if str(value).strip()
            }
    raise RuntimeError(f"No table with column {column!r} found at {url}")


def _nasdaq100_tickers() -> set[str]:
    """Fetch the Nasdaq-100 constituent symbols from Nasdaq's official API."""
    response = requests.get(
        SOURCES["nasdaq100"],
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json()["data"]["data"]["rows"]
    return {
        str(row["symbol"]).strip().upper().replace(".", "-")
        for row in rows
        if str(row.get("symbol", "")).strip()
    }


def main() -> int:
    sp500 = _tickers_from_table(SOURCES["sp500"], "Symbol")
    nasdaq100 = _nasdaq100_tickers()
    tickers = sorted(sp500 | nasdaq100)
    if len(tickers) < 400:
        print(f"Universe looks too small ({len(tickers)} tickers); aborting.")
        return 1

    payload = {
        "description": (
            "Large-cap universe for the SEC 8-K collector: union of the "
            "S&P 500 and Nasdaq-100 constituents. Only these tickers' 8-K "
            "events are collected/exported; everything else is filtered "
            "out before detail fetches and pruned from canonical data."
        ),
        "sources": SOURCES,
        "updated_at": date.today().isoformat(),
        "refresh": (
            "Re-run scripts/update_sec_universe.py and commit the result. "
            "Ticker -> CIK resolution happens at runtime against SEC "
            "company_tickers.json, so no CIKs are stored here."
        ),
        "counts": {
            "sp500": len(sp500),
            "nasdaq100": len(nasdaq100),
            "union": len(tickers),
        },
        "tickers": tickers,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {OUTPUT_PATH}: S&P 500 {len(sp500)} + Nasdaq-100 "
        f"{len(nasdaq100)} -> union {len(tickers)} tickers"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
