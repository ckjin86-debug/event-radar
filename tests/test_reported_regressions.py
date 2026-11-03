import json
from datetime import date, datetime

import pandas as pd
import pytest

from event_radar.backtest.returns import calculate_event_window_returns
from event_radar.backtest.strategies import evaluate_strategies
from event_radar.collectors.news_future import NewsFutureCollector, parse_future_window
from event_radar.collectors.news_future import extract_future_catalyst
from event_radar.export import export_site_data
from event_radar.entity_resolver import ListedCompanyRegistry
from event_radar.models import Event, EventSecurity


@pytest.mark.parametrize('text', ['지난 10월 25일 선고한 판결', '2024년 12월 18일 공장 가동', '지난 8월 인수 계약을 체결했다'])
def test_past_news_dates_are_not_rolled_into_future(text):
    assert parse_future_window(text, date(2026, 11, 3)) is None


@pytest.mark.parametrize('text,want', [
    ('내년 12월 18일 공장 가동 예정', date(2027, 12, 18)),
    ('2028년 3월 공장 상업가동 예정', date(2028, 3, 1)),
    ('오는 4일 선고 예정', date(2026, 11, 4)),
])
def test_year_context_is_preserved(text, want):
    assert parse_future_window(text, date(2026, 11, 3)).start == want


def test_news_selects_future_catalyst_instead_of_historical_background():
    payload = {'items': [{'title': 'LG화학, 신규 공장 계획',
        'description': '2024년 10월 공장을 착공했다. 내년 3월 신규 공장을 상업가동할 예정이다.',
        'originallink': 'https://example.com/news', 'pubDate': 'Tue, 03 Nov 2026 09:00:00 +0900'}]}
    events = NewsFutureCollector(mock_payloads=[payload]).collect(datetime(2026, 11, 1))
    assert len(events) == 1
    assert events[0].event_date == date(2027, 3, 1)
    assert events[0].event_type == 'PLANT_OPERATION'


@pytest.mark.parametrize('text', [
    '지난 6월 원스토어를 인수한 뒤 11월 16일 사명 변경을 주총에 상정한다',
    '계약 기간은 오는 2031년 12월 31일까지로 안정적인 공장 가동 물량을 확보했다',
    '회사는 내년 11월까지 공장 가동률을 높일 계획이다',
])
def test_non_catalyst_dates_and_utilization_are_not_new_events(text):
    assert extract_future_catalyst(text, date(2026, 11, 3)) is None


def test_catalyst_uses_its_own_date_when_sentence_has_multiple_schedules():
    window, kind = extract_future_catalyst('삼성전자, 11월 5일 실적 설명회 열고 12월 1일 공장 가동 예정', date(2026, 11, 3))
    assert kind == 'PLANT_OPERATION'
    assert window.start == date(2026, 12, 1)


def test_undated_catalyst_cannot_borrow_shareholder_meeting_date():
    assert extract_future_catalyst('삼성전자, 11월 5일 주총 개최, 공장 증설은 아직 일정 미정', date(2026, 11, 3)) is None


def _prices(dates):
    return pd.DataFrame({'date': dates, 'close': [100.] * len(dates), 'adj_close': [100.] * len(dates), 'volume': [100] * len(dates)})


def test_missing_d0_cannot_be_replaced_by_last_or_later_price():
    for dates in (['2026-11-02'], ['2026-11-04']):
        frame = calculate_event_window_returns('E', '005930', 'A', date(2026, 11, 3), _prices(dates), _prices(dates))
        assert frame.empty


def test_missing_benchmark_session_does_not_become_zero_return():
    stock = _prices(['2026-11-03', '2026-11-04'])
    frame = calculate_event_window_returns('E', '005930', 'A', date(2026, 11, 3), stock, _prices(['2026-11-03']))
    assert list(frame['offset']) == [0]


def test_strategies_count_event_security_samples_and_compound_benchmark():
    rows = []
    for ticker, price in [('ONE', 120.), ('TWO', 140.)]:
        rows += [dict(event_id='E', ticker=ticker, relation_grade='B', offset=-5, price=100., benchmark_return=-.2),
                 dict(event_id='E', ticker=ticker, relation_grade='B', offset=0, price=price, benchmark_return=0.)]
    result = next(s for s in evaluate_strategies(pd.DataFrame(rows), relation_grade='B') if (s.entry_offset, s.exit_offset) == (-5, 0))
    assert result.sample_n == 2
    assert result.mean_return == pytest.approx(.3)
    assert result.mean_abnormal_return == pytest.approx(.05)  # 0.3 - (1 / 0.8 - 1)


def test_strategy_drawdown_uses_price_path_even_when_trade_is_profitable():
    rows = [dict(event_id='E', ticker='ONE', relation_grade='A', offset=offset,
                 price=price, benchmark_return=0.) for offset, price in [(-5, 100.), (-3, 60.), (0, 110.)]]
    result = next(s for s in evaluate_strategies(pd.DataFrame(rows)) if (s.entry_offset, s.exit_offset) == (-5, 0))
    assert result.max_drawdown == pytest.approx(.4)


def test_resolved_tickers_are_exported_even_when_primary_is_blank(tmp_path):
    now = datetime(2026, 11, 3)
    event = Event(event_id='E', country='KR', event_type='COURT_RULING', event_name='한화시스템 11월 6일 선고',
        primary_company='흥국생명', primary_ticker='', event_date=date(2026, 11, 6), announced_at=now,
        source_name='NEWS_FUTURE', source_kind='SECONDARY', first_seen_at=now, last_seen_at=now)
    secs = ListedCompanyRegistry({'한화시스템': '272210'}).resolve_mentions(event)
    export_site_data([event], [], {'E': secs}, {}, None, {}, {}, output_dir=tmp_path, now=now)
    row = json.loads((tmp_path / 'events.json').read_text('utf-8'))[0]
    assert row['ticker'] == '272210'
    assert row['related_securities'][0]['ticker'] == '272210'
    assert secs[0].relation_known_date == date(2026, 11, 3)
    assert secs[0].evidence_source == 'NEWS_FUTURE'
