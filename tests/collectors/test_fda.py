from datetime import date, datetime

from bs4 import BeautifulSoup
from event_radar.collectors.fda import FdaCollector


class FakeResponse:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class FdaFallbackSession:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}
        self.urls = []

    def get(self, url, timeout=None, params=None):
        self.urls.append(url)
        if "fda.gov" in url:
            return FakeResponse(404, "not found")
        if "federalregister.gov" in url:
            return FakeResponse(200, payload=self.payload)
        return FakeResponse(500)


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
    collector = FdaCollector(mock_html=html)
    assert collector._ticker_and_company("Drug Advisory Meeting for BioCorp (NASDAQ: BCRP)") == ("BCRP", "BioCorp")
    parsed = collector._parse_advisory_table(BeautifulSoup(html, "html.parser"), datetime(2026, 11, 1))
    assert len(parsed) == 1
    event = parsed[0]
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


def test_fda_falls_back_to_federal_register_when_calendar_returns_404():
    payload = {
        "results": [
            {
                "title": "Oncologic Drugs Advisory Committee; Notice of Meeting",
                "abstract": "FDA announces a forthcoming public advisory committee meeting.",
                "document_number": "2026-22222",
                "html_url": "https://www.federalregister.gov/documents/2026/10/20/2026-22222/example",
                "publication_date": "2026-10-20",
                "excerpts": "DATES: The meeting will be held on November 19, 2026, from 9:00 a.m. to 5:00 p.m. Eastern Time.",
            }
        ]
    }
    collector = FdaCollector()
    collector.session = FdaFallbackSession(payload)

    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 1
    event = events[0]
    assert event.event_date == date(2026, 11, 19)
    assert event.event_type == "FDA_ADVISORY_COMMITTEE"
    assert event.source_url.startswith("https://www.federalregister.gov/")
    assert event.source_event_uid == "federal-register:2026-22222"
    assert any("federalregister.gov" in url for url in collector.session.urls)


def test_federal_register_fallback_ignores_non_meeting_and_past_items():
    payload = {
        "results": [
            {
                "title": "Request for Nominations for FDA Advisory Committees",
                "document_number": "2026-11111",
                "html_url": "https://www.federalregister.gov/documents/2026/10/01/2026-11111/example",
                "publication_date": "2026-10-01",
                "excerpts": "Nominations will be accepted through December 31, 2026.",
            },
            {
                "title": "Pediatric Advisory Committee; Notice of Meeting",
                "document_number": "2026-11112",
                "html_url": "https://www.federalregister.gov/documents/2026/07/28/2026-11112/example",
                "publication_date": "2026-07-28",
                "excerpts": "DATES: The meeting will be held virtually on September 16, 2026, from 10:00 a.m. to 4:00 p.m. Eastern Time.",
            },
        ]
    }
    events = FdaCollector()._parse_federal_register_payload(payload, datetime(2026, 11, 1))
    assert events == []
