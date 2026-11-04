from datetime import date

import pandas as pd

from event_radar.prices.base import CachedPriceProvider


class RecordingProvider:
    def __init__(self):
        self.calls = []

    def history(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        dates = pd.date_range(start=start, end=end, freq="D")
        return pd.DataFrame({
            "date": dates.date,
            "open": range(100, 100 + len(dates)),
            "high": range(101, 101 + len(dates)),
            "low": range(99, 99 + len(dates)),
            "close": range(100, 100 + len(dates)),
            "adj_close": range(100, 100 + len(dates)),
            "volume": [1000] * len(dates),
        })


def _seed_cache(path, start, end):
    dates = pd.date_range(start=start, end=end, freq="D")
    df = pd.DataFrame({
        "date": dates.date,
        "open": [90] * len(dates),
        "high": [91] * len(dates),
        "low": [89] * len(dates),
        "close": [90] * len(dates),
        "adj_close": [90] * len(dates),
        "volume": [900] * len(dates),
    })
    df.to_csv(path, index=False)


def test_partial_tail_cache_fetches_only_missing_tail(tmp_path):
    delegate = RecordingProvider()
    cached = CachedPriceProvider(delegate, tmp_path)
    cache_path = cached._cache_path("005930")
    _seed_cache(cache_path, date(2026, 10, 1), date(2026, 11, 1))

    result = cached.history("005930", date(2026, 10, 15), date(2026, 11, 3))

    assert delegate.calls == [("005930", date(2026, 11, 2), date(2026, 11, 3))]
    assert result["date"].min() == date(2026, 10, 15)
    assert result["date"].max() == date(2026, 11, 3)


def test_partial_head_cache_fetches_only_missing_head(tmp_path):
    delegate = RecordingProvider()
    cached = CachedPriceProvider(delegate, tmp_path)
    cache_path = cached._cache_path("005930")
    _seed_cache(cache_path, date(2026, 10, 15), date(2026, 11, 3))

    cached.history("005930", date(2026, 10, 10), date(2026, 11, 1))

    assert delegate.calls == [("005930", date(2026, 10, 10), date(2026, 10, 14))]


def test_complete_cache_makes_no_delegate_call(tmp_path):
    delegate = RecordingProvider()
    cached = CachedPriceProvider(delegate, tmp_path)
    cache_path = cached._cache_path("005930")
    _seed_cache(cache_path, date(2026, 10, 1), date(2026, 11, 3))

    cached.history("005930", date(2026, 10, 15), date(2026, 11, 1))

    assert delegate.calls == []


def test_disjoint_cache_blocks_do_not_hide_an_interior_request(tmp_path):
    delegate = RecordingProvider()
    cached = CachedPriceProvider(delegate, tmp_path)
    path = cached._cache_path('^KS11')
    _seed_cache(path, date(2009, 12, 1), date(2009, 12, 31))
    first = pd.read_csv(path)
    _seed_cache(path, date(2026, 10, 1), date(2026, 11, 3))
    pd.concat([first, pd.read_csv(path)]).to_csv(path, index=False)
    frame = cached.history('^KS11', date(2024, 7, 1), date(2024, 7, 31))
    assert len(frame) == 31
    assert delegate.calls == [('^KS11', date(2024, 7, 1), date(2024, 7, 31))]
