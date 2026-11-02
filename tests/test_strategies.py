import pytest
import pandas as pd
from event_radar.backtest.strategies import (
    PREDEFINED_STRATEGIES,
    evaluate_strategies,
    calculate_robustness_score,
    StrategyResult,
)


def make_multi_event_returns():
    # 5 events with returns at offsets -30, -20, -10, -5, -1, 0, 3, 5
    rows = []
    offsets = [-30, -20, -10, -5, -1, 0, 3, 5]
    for ev_id in ["E1", "E2", "E3", "E4", "E5"]:
        for off in offsets:
            # Baseline trending upward into D0
            p = 100.0 * (1.0 + off * 0.005)
            rows.append({
                "event_id": ev_id,
                "ticker": "005930",
                "relation_grade": "A",
                "offset": off,
                "price": p,
                "return_from_d0": (p - 100.0) / 100.0,
                "benchmark_return": (off * 0.002),
                "abnormal_return": (p - 100.0) / 100.0 - (off * 0.002),
            })
    return pd.DataFrame(rows)


def test_evaluates_exact_predefined_strategies():
    df = make_multi_event_returns()
    results = evaluate_strategies(df, event_type="BONUS_ISSUE", relation_grade="A")

    assert len(results) == len(PREDEFINED_STRATEGIES)
    assert len(results) == 9

    pairs = [(r.entry_offset, r.exit_offset) for r in results]
    assert (-30, 0) in pairs
    assert (-20, -5) in pairs
    assert (-10, -1) in pairs
    assert (0, 5) in pairs


def test_robustness_score_penalty_when_adjacent_is_opposite():
    best = StrategyResult(
        event_type="BONUS_ISSUE",
        relation_grade="A",
        entry_offset=-20,
        exit_offset=-5,
        sample_n=10,
        mean_return=0.10,
        median_return=0.09,
        win_rate=0.8,
        mean_abnormal_return=0.08,
        median_abnormal_return=0.07,
        stdev=0.04,
        max_loss=-0.02,
        max_drawdown=0.05,
    )

    # Adjacent strategies are positive -> high robustness
    positive_adjacent = [
        StrategyResult(
            event_type="BONUS_ISSUE",
            relation_grade="A",
            entry_offset=-30,
            exit_offset=-5,
            mean_abnormal_return=0.06,
            median_abnormal_return=0.05,
        ),
        StrategyResult(
            event_type="BONUS_ISSUE",
            relation_grade="A",
            entry_offset=-20,
            exit_offset=0,
            mean_abnormal_return=0.05,
            median_abnormal_return=0.04,
        ),
    ]

    # Adjacent strategies are sharply negative -> low robustness
    negative_adjacent = [
        StrategyResult(
            event_type="BONUS_ISSUE",
            relation_grade="A",
            entry_offset=-30,
            exit_offset=-5,
            mean_abnormal_return=-0.08,
            median_abnormal_return=-0.07,
        ),
        StrategyResult(
            event_type="BONUS_ISSUE",
            relation_grade="A",
            entry_offset=-20,
            exit_offset=0,
            mean_abnormal_return=-0.05,
            median_abnormal_return=-0.04,
        ),
    ]

    score_pos = calculate_robustness_score(best, positive_adjacent)
    score_neg = calculate_robustness_score(best, negative_adjacent)

    assert score_pos > score_neg
    assert score_pos >= 0.7
    assert score_neg <= 0.4
