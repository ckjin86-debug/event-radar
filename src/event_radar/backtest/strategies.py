"""Predefined event trading strategy evaluation and robustness scoring."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd


PREDEFINED_STRATEGIES: list[tuple[int, int]] = [
    (-30, 0),
    (-30, -5),
    (-20, 0),
    (-20, -5),
    (-10, 0),
    (-10, -1),
    (-5, 0),
    (-5, 3),
    (0, 5),
]


@dataclass
class StrategyResult:
    event_type: str
    relation_grade: str
    entry_offset: int
    exit_offset: int
    sample_n: int = 0
    mean_return: float = 0.0
    median_return: float = 0.0
    win_rate: float = 0.0
    mean_abnormal_return: float = 0.0
    median_abnormal_return: float = 0.0
    stdev: float = 0.0
    max_loss: float = 0.0
    max_drawdown: float = 0.0
    robustness_score: float = 0.0


def calculate_robustness_score(
    target: StrategyResult,
    adjacent_strategies: list[StrategyResult],
) -> float:
    """Calculate robustness score [0.0 - 1.0] checking consistency across neighboring windows."""
    if not adjacent_strategies:
        return 0.5

    target_dir = 1.0 if target.mean_abnormal_return >= 0 else -1.0
    consistent_count = 0
    total = len(adjacent_strategies)

    for adj in adjacent_strategies:
        adj_dir = 1.0 if adj.mean_abnormal_return >= 0 else -1.0
        if adj_dir == target_dir:
            consistent_count += 1

    directional_score = consistent_count / total

    # Mean vs Median divergence penalty
    divergence = abs(target.mean_abnormal_return - target.median_abnormal_return)
    divergence_penalty = min(0.3, divergence * 2.0)

    score = directional_score * 0.8 + 0.2 - divergence_penalty
    return round(float(np.clip(score, 0.0, 1.0)), 2)


def get_adjacent_strategies(
    entry: int,
    exit: int,
    all_strategies: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Find adjacent strategies that share entry or exit or are close in offsets."""
    adjacent = []
    for e, x in all_strategies:
        if (e, x) == (entry, exit):
            continue
        # Share exit or share entry, or close
        if e == entry or x == exit or abs(e - entry) <= 15 and abs(x - exit) <= 5:
            adjacent.append((e, x))
    return adjacent


def evaluate_strategies(
    event_returns: pd.DataFrame,
    event_type: str = "ALL",
    relation_grade: str = "A",
) -> list[StrategyResult]:
    """Evaluate 9 predefined strategies on historical event return profiles."""
    if event_returns.empty:
        return [
            StrategyResult(event_type=event_type, relation_grade=relation_grade, entry_offset=e, exit_offset=x)
            for e, x in PREDEFINED_STRATEGIES
        ]

    results: list[StrategyResult] = []

    # Filter grade if specified
    df = event_returns.copy()
    if "relation_grade" in df.columns and relation_grade != "ALL":
        df = df[df["relation_grade"] == relation_grade]

    # Each security is an independent price series within an event.
    sample_columns = ["event_id", "ticker"] if "ticker" in df.columns else ["event_id"]
    samples = [frame.set_index("offset") for _, frame in df.groupby(sample_columns)]

    for entry, exit_off in PREDEFINED_STRATEGIES:
        strat_returns = []
        strat_abnormal = []
        strat_drawdowns = []

        for indexed in samples:
            try:
                row_in = indexed.loc[entry]
                row_out = indexed.loc[exit_off]
            except KeyError:
                continue

            p_in = float(row_in["price"])
            p_out = float(row_out["price"])
            if not np.isfinite(p_in) or not np.isfinite(p_out) or p_in <= 0 or p_out <= 0:
                continue

            ret = (p_out - p_in) / p_in
            bm_ret_in = float(row_in["benchmark_return"])
            bm_ret_out = float(row_out["benchmark_return"])
            if not np.isfinite(bm_ret_in) or not np.isfinite(bm_ret_out) or bm_ret_in <= -1:
                continue
            bm_period_ret = (1 + bm_ret_out) / (1 + bm_ret_in) - 1
            abnormal_ret = ret - bm_period_ret

            strat_returns.append(ret)
            strat_abnormal.append(abnormal_ret)
            path = indexed.loc[(indexed.index >= entry) & (indexed.index <= exit_off), "price"].sort_index().astype(float)
            path = path[np.isfinite(path) & (path > 0)]
            strat_drawdowns.append(float((1 - path / path.cummax()).max()))

        n = len(strat_returns)
        if n == 0:
            results.append(
                StrategyResult(
                    event_type=event_type,
                    relation_grade=relation_grade,
                    entry_offset=entry,
                    exit_offset=exit_off,
                    sample_n=0,
                )
            )
            continue

        ret_series = pd.Series(strat_returns)
        ab_series = pd.Series(strat_abnormal)
        win_rate = float((ab_series > 0).sum() / n)

        results.append(
            StrategyResult(
                event_type=event_type,
                relation_grade=relation_grade,
                entry_offset=entry,
                exit_offset=exit_off,
                sample_n=n,
                mean_return=round(float(ret_series.mean()), 4),
                median_return=round(float(ret_series.median()), 4),
                win_rate=round(win_rate, 4),
                mean_abnormal_return=round(float(ab_series.mean()), 4),
                median_abnormal_return=round(float(ab_series.median()), 4),
                stdev=round(float(ret_series.std(ddof=1)) if n > 1 else 0.0, 4),
                max_loss=round(float(ret_series.min()), 4),
                max_drawdown=round(max(strat_drawdowns), 4),
            )
        )

    # Compute robustness scores for each
    strategy_map = {(r.entry_offset, r.exit_offset): r for r in results}
    all_pairs = list(strategy_map.keys())

    for r in results:
        adj_pairs = get_adjacent_strategies(r.entry_offset, r.exit_offset, all_pairs)
        adj_results = [strategy_map[p] for p in adj_pairs if p in strategy_map]
        r.robustness_score = calculate_robustness_score(r, adj_results)

    return results
