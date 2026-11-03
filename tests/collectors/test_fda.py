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
    def __init__(self, search_payload, detail_payloads=None):
        self.search_payload = search_payload
        self.detail_payloads = detail_payloads or {}
        self.headers = {}
        self.urls = []

    def get(self, url, timeout=None, params=None):
        self.urls.append(url)
        if "fda.gov" in url:
            return FakeResponse(404, "not found")
        if "/api/v1/documents.json" in url:
            return FakeResponse(200, payload=self.search_payload)
        if "/api/v1/documents/" in url and url.endswith(".json"):
            doc_no = url.rsplit("/", 1)[-1].removesuffix(".json")
            payload = self.detail_payloads.get(doc_no)
            return FakeResponse(200 if payload else 404, payload=payload)
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
    events = FdaCollector(mock_html=html).collect(since=datetime(2026, 11, 1))

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
    assert parsed[0].primary_ticker == "BCRP"
    assert parsed[0].primary_company == "BioCorp"


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


def test_fda_fallback_reads_meeting_date_from_federal_register_detail():
    search_payload = {
        "results": [
            {
                "title": "Oncologic Drugs Advisory Committee; Notice of Meeting",
                "document_number": "2026-22222",
                "html_url": "https://www.federalregister.gov/documents/2026/10/20/2026-22222/example",
                "publication_date": "2026-10-20",
            }
        ]
    }
    detail_payloads = {
        "2026-22222": {
            "title": "Oncologic Drugs Advisory Committee; Notice of Meeting",
            "document_number": "2026-22222",
            "html_url": "https://www.federalregister.gov/documents/2026/10/20/2026-22222/example",
            "publication_date": "2026-10-20",
            "dates": "The meeting will be held on November 19, 2026, from 9:00 a.m. to 5:00 p.m. Eastern Time.",
        }
    }
    collector = FdaCollector()
    collector.session = FdaFallbackSession(search_payload, detail_payloads)

    events = collector.collect(since=datetime(2026, 11, 1))

    assert len(events) == 1
    event = events[0]
    assert event.event_date == date(2026, 11, 19)
    assert event.event_type == "FDA_ADVISORY_COMMITTEE"
    assert event.source_url.startswith("https://www.federalregister.gov/")
    assert event.source_event_uid == "federal-register:2026-22222"
    assert any("/api/v1/documents/2026-22222.json" in url for url in collector.session.urls)


def test_federal_register_detail_fallback_ignores_non_meeting_and_past_items():
    search_payload = {
        "results": [
            {
                "title": "Request for Nominations for FDA Advisory Committees",
                "document_number": "2026-11111",
            },
            {
                "title": "Pediatric Advisory Committee; Notice of Meeting",
                "document_number": "2026-11112",
            },
        ]
    }
    detail_payloads = {
        "2026-11112": {
            "title": "Pediatric Advisory Committee; Notice of Meeting",
            "document_number": "2026-11112",
            "html_url": "https://www.federalregister.gov/documents/2026/07/28/2026-11112/example",
            "publication_date": "2026-07-28",
            "dates": "The meeting will be held virtually on September 16, 2026, from 10:00 a.m. to 4:00 p.m. Eastern Time.",
        }
    }
    collector = FdaCollector()
    collector.session = FdaFallbackSession(search_payload, detail_payloads)
    assert collector._fetch_federal_register_events(datetime(2026, 11, 1)) == []
    assert not any("2026-11111.json" in url for url in collector.session.urls)
