import pytest
from event_radar.scoring import (
    ScoreInput,
    ScoreResult,
    calculate_event_score,
    load_score_config,
)


def test_sample_size_penalty_caps_historical_edge_at_5_when_n_less_than_3():
    inp = ScoreInput(
        status="CONFIRMED",
        relation_score=100,
        sample_n=2,  # N < 3 !
        median_abnormal_return=0.20,  # huge 20%
        win_rate=1.0,  # 100% win rate
        robustness_score=1.0,
        recent_runup=0.0,
        volume_trend=1.0,
    )

    res = calculate_event_score(inp)
    # Historical edge must be strictly capped at 5 points due to low sample penalty
    assert res.edge_points <= 5
    assert res.total_score <= (20 + 20 + 5 + 15 + 15)


def test_confirmed_status_scores_higher_than_expected():
    inp_conf = ScoreInput(status="CONFIRMED", relation_score=100, sample_n=10)
    inp_exp = ScoreInput(status="EXPECTED", relation_score=100, sample_n=10)

    res_conf = calculate_event_score(inp_conf)
    res_exp = calculate_event_score(inp_exp)

    assert res_conf.schedule_points == 20
    assert res_exp.schedule_points == 10
    assert res_conf.total_score > res_exp.total_score


def test_relation_score_scales_directness_points():
    inp_a = ScoreInput(status="CONFIRMED", relation_score=100)
    inp_b = ScoreInput(status="CONFIRMED", relation_score=75)

    res_a = calculate_event_score(inp_a)
    res_b = calculate_event_score(inp_b)

    assert res_a.relation_points == 20
    assert res_b.relation_points == 15  # round(75 * 0.20)


def test_total_score_clamped_0_to_100():
    # Extreme negative
    inp_low = ScoreInput(
        status="RUMORED",
        relation_score=0,
        sample_n=0,
        median_abnormal_return=-0.5,
        win_rate=0.0,
        robustness_score=0.0,
        recent_runup=0.8,  # severe over-runup
    )
    res_low = calculate_event_score(inp_low)
    assert res_low.total_score >= 0

    # Extreme positive
    inp_high = ScoreInput(
        status="CONFIRMED",
        relation_score=100,
        sample_n=50,
        median_abnormal_return=0.3,
        win_rate=1.0,
        robustness_score=1.0,
        recent_runup=0.0,
        volume_trend=2.0,
    )
    res_high = calculate_event_score(inp_high)
    assert res_high.total_score <= 100
