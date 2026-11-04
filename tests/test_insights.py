from datetime import date, datetime

import pandas as pd
import pytest

from event_radar.backtest.metrics import summarize_event_group
from event_radar.models import Event, EventSecurity


def event(precision='EXACT_DATE'):
    return Event(event_id='E', country='KR', primary_company='한빛전자', primary_ticker='111111', event_type='CAPEX',
        event_name='신공장 가동', event_date=date(2026, 11, 6), date_precision=precision, status='CONFIRMED',
        announced_at=datetime(2026, 11, 1), source_name='DART', source_url='https://example.com/source',
        first_seen_at=datetime(2026, 11, 1), last_seen_at=datetime(2026, 11, 1))


def test_missing_market_and_history_do_not_receive_default_points():
    from event_radar.insights import build_insight
    security = EventSecurity(event_id='E', ticker='111111', relation_grade='A', relation_score=100, relation_type='DIRECT')
    out = build_insight(event(), [security], date(2026, 11, 3), coverage={}, summary=None, market=None)
    assert out['components']['market']['points'] == 0
    assert out['components']['history']['points'] == 0
    assert out['market'] is None
    assert out['tier'] != 'FOCUS'
    assert out['missing']


def test_many_stocks_in_one_event_do_not_increase_historical_confidence():
    from event_radar.insights import build_insight
    coverage = dict(eligible_events=1, priced_events=1, complete_events=1, security_samples=20)
    out = build_insight(event(), [], date(2026, 11, 3), coverage, None, None)
    assert out['components']['history']['points'] <= 5
    assert out['history_confidence'] == 'LIMITED'


def test_period_schedule_has_lower_schedule_confidence_than_exact_date():
    from event_radar.insights import build_insight
    exact = build_insight(event(), [], date(2026, 11, 3), {}, None, None)
    broad = build_insight(event('YEAR'), [], date(2026, 11, 3), {}, None, None)
    assert exact['components']['schedule']['points'] > broad['components']['schedule']['points']


def test_event_weighted_mean_does_not_overweight_one_event_with_many_tickers():
    rows = [dict(event_id='ONE', ticker=str(i), offset=5, return_from_d0=.2, abnormal_return=.2) for i in range(10)]
    rows.append(dict(event_id='TWO', ticker='other', offset=5, return_from_d0=-.1, abnormal_return=-.1))
    summary = summarize_event_group(pd.DataFrame(rows), target_offset=5)
    assert summary.sample_n == 11
    assert summary.event_n == 2
    assert summary.mean_return == pytest.approx(.05)
    assert summary.win_rate == pytest.approx(.5)


def test_strategy_performance_also_weights_events_equally():
    from event_radar.backtest.strategies import evaluate_strategies
    rows = []
    for ev_id, ticker, end in [('ONE', str(i), 120.) for i in range(10)] + [('TWO', 'other', 90.)]:
        rows += [dict(event_id=ev_id, ticker=ticker, relation_grade='A', offset=-5, price=100., benchmark_return=0.),
                 dict(event_id=ev_id, ticker=ticker, relation_grade='A', offset=0, price=end, benchmark_return=0.)]
    strategy = next(s for s in evaluate_strategies(pd.DataFrame(rows)) if (s.entry_offset, s.exit_offset) == (-5, 0))
    assert strategy.sample_n == 11
    assert strategy.event_n == 2
    assert strategy.mean_return == pytest.approx(.05)


def test_market_snapshot_rejects_stale_prices_and_measures_actual_runup():
    from event_radar.insights import market_snapshot
    prices = pd.DataFrame(dict(date=pd.bdate_range('2026-10-01', periods=23), adj_close=list(range(100,123)), volume=[100]*22+[200]))
    snap = market_snapshot(prices, date(2026, 11, 3))
    assert snap['return_20d'] == pytest.approx(122/102-1, abs=1e-6)
    assert snap['volume_ratio_20d'] == pytest.approx(2.)
    assert market_snapshot(prices, date(2026, 12, 1)) is None
