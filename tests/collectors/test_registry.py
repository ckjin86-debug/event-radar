from datetime import datetime, date
import pytest
from event_radar.collectors.fda import FdaCollector
from event_radar.collectors.entertainment import EntertainmentCollector
from event_radar.collectors.games import GamesCollector


def test_fda_collector_parses_html():
    html = """
    <div class="view-content">
      <div class="views-row">
        <div class="views-field-title">
          <a href="/drugs/approval/123">FDA Approves New Cancer Drug for BioCorp (Ticker: BCRP) on 2026-11-20</a>
        </div>
      </div>
    </div>
    """
    collector = FdaCollector(mock_html=html)
    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 1
    assert events[0].event_type == "FDA_APPROVAL"
    assert events[0].primary_ticker == "BCRP"
    assert events[0].event_date == date(2026, 11, 20)
    assert events[0].country == "US"


def test_entertainment_collector_artist_mapping():
    html = """
    <div class="notice-list">
      <div class="notice-item">
        <span class="title">[공지] 방탄소년단 신규 앨범 컴백 일정 안내 (2026.11.25)</span>
        <a class="link" href="https://weverse.io/bts/notice/100">원문보기</a>
      </div>
    </div>
    """
    collector = EntertainmentCollector(mock_html=html)
    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 1
    assert events[0].event_type == "ENTERTAINMENT"
    assert events[0].primary_ticker == "352820"
    assert events[0].primary_company == "하이브"
    assert events[0].event_date == date(2026, 11, 25)


def test_games_collector_publisher_mapping():
    html = """
    <div class="schedule-list">
      <div class="game-item">
        <span class="game-name">인조이(inZOI) 글로벌 얼리액세스 출시일 확정 2026.12.01</span>
        <a href="https://inven.co.kr/game/inzoi">링크</a>
      </div>
    </div>
    """
    collector = GamesCollector(mock_html=html)
    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 1
    assert events[0].event_type == "GAME_RELEASE"
    assert events[0].primary_ticker == "259960"
    assert events[0].primary_company == "크래프톤"
    assert events[0].event_date == date(2026, 12, 1)


def test_selector_failure_logs_failed_without_crashing():
    # Broken html where container or title selector does not exist
    broken_html = "<html><body>No matching elements</body></html>"
    collector = FdaCollector(mock_html=broken_html)

    # Must return empty list, not crash
    events = collector.collect(since=datetime(2026, 11, 1))
    assert events == []
