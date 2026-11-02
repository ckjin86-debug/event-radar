"""Configurable Event Score (0-100) calculation engine."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class ScoreInput:
    status: str = "CONFIRMED"
    relation_score: int = 100
    sample_n: int = 0
    median_abnormal_return: float = 0.0
    win_rate: float = 0.0
    robustness_score: float = 0.5
    recent_runup: float = 0.0
    volume_trend: float = 1.0


@dataclass
class ScoreResult:
    total_score: int
    schedule_points: int
    relation_points: int
    edge_points: int
    robustness_points: int
    setup_points: int


def load_score_config(path: Path | str = "config/score.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, mode="r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def calculate_event_score(inp: ScoreInput, config: Optional[dict] = None) -> ScoreResult:
    """Calculate 100-point event score based on 5 key pillars."""
    if config is None:
        config = load_score_config()

    sched_map = config.get("schedule_scores", {
        "CONFIRMED": 20,
        "EXPECTED": 10,
        "RUMORED": 0,
        "CANCELLED": 0,
    })

    # A. Schedule Certainty (0 - 20)
    sched_pts = int(sched_map.get(inp.status.upper(), 0))

    # B. Relation Directness (0 - 20)
    rel_pts = int(round(inp.relation_score * 0.20))
    rel_pts = max(0, min(20, rel_pts))

    # C. Historical Edge (0 - 30) with sample penalty
    sample_caps = config.get("sample_penalty_caps", {
        "min_n_3": 5,
        "min_n_8": 15,
        "min_n_15": 24,
        "full_cap": 30,
    })

    n = inp.sample_n
    if n < 3:
        max_edge_allowed = sample_caps.get("min_n_3", 5)
    elif n < 8:
        max_edge_allowed = sample_caps.get("min_n_8", 15)
    elif n < 15:
        max_edge_allowed = sample_caps.get("min_n_15", 24)
    else:
        max_edge_allowed = sample_caps.get("full_cap", 30)

    # 1. Abnormal return component (0 - 15)
    target_ret = 0.10
    ret_ratio = max(0.0, min(1.0, inp.median_abnormal_return / target_ret)) if target_ret > 0 else 0.0
    ret_pts = ret_ratio * 15.0

    # 2. Win rate component (0 - 10)
    # Win rate above 50% contributes
    if inp.win_rate > 0.50:
        win_pts = ((inp.win_rate - 0.50) / 0.50) * 10.0
    else:
        win_pts = 0.0
    win_pts = max(0.0, min(10.0, win_pts))

    # 3. Sample size bonus (0 - 5)
    sample_pts = min(5.0, (n / 20.0) * 5.0)

    raw_edge = ret_pts + win_pts + sample_pts
    edge_pts = int(round(min(raw_edge, float(max_edge_allowed))))

    # D. Robustness (0 - 15)
    rob_pts = int(round(max(0.0, min(1.0, inp.robustness_score)) * 15.0))

    # E. Current Setup (0 - 15)
    setup_base = 10.0
    # Over-runup penalty
    if inp.recent_runup > 0.20:
        setup_base -= min(5.0, (inp.recent_runup - 0.20) * 20.0)
    # Volume activity bonus
    if 1.0 <= inp.volume_trend <= 3.0:
        setup_base += 2.0
    setup_pts = int(round(max(0.0, min(15.0, setup_base))))

    total = sched_pts + rel_pts + edge_pts + rob_pts + setup_pts
    total = max(0, min(100, total))

    return ScoreResult(
        total_score=total,
        schedule_points=sched_pts,
        relation_points=rel_pts,
        edge_points=edge_pts,
        robustness_points=rob_pts,
        setup_points=setup_pts,
    )
