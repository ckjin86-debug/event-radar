from datetime import date, datetime

from event_radar.collectors.fda import FdaCollector


def test_fda_advisory_calendar_emits_confirmed_meeting_with_sector_proxy():
    html = """
    <table>
      <thead><tr><th>Date</th><th>Committee / Meeting</th></tr></thead>
      <tbody>
        <tr>
          <td>11/19/2026 09:00 AM EST</td>
          <td><a href="/advisory-committees/advisory-committee-calendar/november-19-2026-meeting">Oncologic Drugs Advisory Committee Meeting</a></td>
        </tr>
      </tbody>
    </table>
    """
    collector = FdaCollector(mock_html=html)
    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "FDA_ADVISORY_COMMITTEE"
    assert event.event_date == date(2026, 11, 19)
    assert event.date_precision == "EXACT_DATE"
    assert event.status == "CONFIRMED"
    assert event.primary_ticker == "XBI"
    assert event.source_name == "FDA_ADVISORY"


def test_fda_advisory_calendar_uses_explicit_ticker_when_present():
    html = """
    <table><tbody>
      <tr>
        <td>12/03/2026 10:00 AM EST</td>
        <td><a href="/meeting/abc">Drug Advisory Meeting for BioCorp (NASDAQ: BCRP)</a></td>
      </tr>
    </tbody></table>
    """
    event = FdaCollector(mock_html=html).collect(since=datetime(2026, 11, 1))[0]
    assert event.primary_ticker == "BCRP"
    assert event.primary_company == "BioCorp"


def test_fda_advisory_calendar_ignores_past_rows_before_since():
    html = """
    <table><tbody>
      <tr><td>10/01/2026 09:00 AM EST</td><td>Old Advisory Committee Meeting</td></tr>
      <tr><td>11/20/2026 09:00 AM EST</td><td>Future Advisory Committee Meeting</td></tr>
    </tbody></table>
    """
    events = FdaCollector(mock_html=html).collect(since=datetime(2026, 11, 1))
    assert len(events) == 1
    assert events[0].event_date == date(2026, 11, 20)
