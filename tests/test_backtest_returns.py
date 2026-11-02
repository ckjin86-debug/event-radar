from datetime import date, timedelta
import pytest
import pandas as pd
import numpy as np
from event_radar.backtest.returns import calculate_event_window_returns
from event_radar.backtest.metrics import summarize_event_group, BacktestSummary


def make_dummy_price_df(start_date: date, n_days: int, start_price: float, daily_ret: float = 0.01):
    dates = []
    prices = []
    volumes = []
    curr_date = start_date
    curr_price = start_price

    while len(dates) < n_days:
        if curr_date.weekday() < 5:  # skip weekends
            dates.append(curr_date)
            prices.append(curr_price)
            volumes.append(100000)
            curr_price *= (1 + daily_ret)
        curr_date += timedelta(days=1)

    return pd.DataFrame({
        "date": dates,
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "adj_close": prices,
        "volume": volumes,
    })


def test_event_window_offsets_and_abnormal_returns():
    # 100 trading days
    stock_df = make_dummy_price_df(date(2026, 1, 1), 100, 100.0, daily_ret=0.02)
    bm_df = make_dummy_price_df(date(2026, 1, 1), 100, 200.0, daily_ret=0.01)

    # Choose day index 60 as D0
    d0_date = stock_df.iloc[60]["date"]

    res = calculate_event_window_returns(
        event_id="EVT_TEST",
        ticker="005930",
        relation_grade="A",
        event_session_date=d0_date,
        stock_prices=stock_df,
        benchmark_prices=bm_df,
    )

    assert not res.empty
    assert "offset" in res.columns
    assert "return_from_d0" in res.columns
    assert "abnormal_return" in res.columns

    # D0 offset should be 0
    d0_row = res[res["offset"] == 0].iloc[0]
    assert d0_row["return_from_d0"] == pytest.approx(0.0, abs=1e-5)
    assert d0_row["benchmark_return"] == pytest.approx(0.0, abs=1e-5)
    assert d0_row["abnormal_return"] == pytest.approx(0.0, abs=1e-5)

    # Offset range within -60 to +20
    assert res["offset"].min() >= -60
    assert res["offset"].max() <= 20

    # Stock grew 2% per day, benchmark 1% per day -> positive abnormal return for positive offset
    p5_row = res[res["offset"] == 5].iloc[0]
    assert p5_row["abnormal_return"] > 0


def test_summarize_event_group_metrics():
    # Multi-event returns at offset +5
    df = pd.DataFrame([
        {"event_id": "E1", "offset": 5, "return_from_d0": 0.10, "abnormal_return": 0.08},
        {"event_id": "E2", "offset": 5, "return_from_d0": 0.05, "abnormal_return": 0.03},
        {"event_id": "E3", "offset": 5, "return_from_d0": -0.02, "abnormal_return": -0.04},
        {"event_id": "E4", "offset": 5, "return_from_d0": 0.08, "abnormal_return": 0.06},
    ])

    summary = summarize_event_group(df, target_offset=5)
    assert summary.sample_n == 4
    assert summary.win_rate == pytest.approx(0.75)  # 3 positive abnormal returns out of 4
    assert summary.mean_return == pytest.approx(0.0525)
    assert summary.mean_abnormal_return == pytest.approx(0.0325)
    assert summary.max_gain == 0.10
    assert summary.max_loss == -0.02
