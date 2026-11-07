from datetime import datetime, date
import json
from pathlib import Path
from event_radar.collectors.sec import SecCollector


FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "sec" / "sample_submissions.json"

MASTER_INDEX = """Description: Master Index of EDGAR Dissemination Feed
CIK|Company Name|Form Type|Date Filed|File Name
320193|Apple Inc.|8-K|2026-11-03|edgar/data/320193/0000320193-26-000101.txt
320193|Apple Inc.|8-K/A|2026-11-03|edgar/data/320193/0000320193-26-000102.txt
789019|Microsoft Corp|10-Q|2026-11-03|edgar/data/789019/0000789019-26-000999.txt
1652044|Alphabet Inc.|8-K|2026-11-03|edgar/data/1652044/0001652044-26-000777.txt
"""

COMPANY_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
}


def test_sec_collector_parses_fixtures():
    collector = SecCollector(fixture_path=FIXTURE_PATH)

    events = collector.collect(since=datetime(2026, 10, 1))
    assert len(events) == 2

    evt1 = [e for e in events if e.event_type == "EARNINGS"][0]
    assert evt1.primary_ticker == "AAPL"
    assert evt1.country == "US"
    assert evt1.source_event_uid == "0000320193-26-000101"
    assert evt1.event_time_context == "AFTERHOURS"

    evt2 = [e for e in events if e.event_type == "STOCK_SPLIT"][0]
    assert evt2.primary_ticker == "AAPL"
    assert evt2.event_date == date(2026, 11, 20)
    assert evt2.source_event_uid == "0000320193-26-000102"


def test_sec_collector_user_agent_format():
    collector = SecCollector()
    ua = collector.session.headers.get("User-Agent", "")
    assert "@" in ua
    assert len(ua.split()) >= 2


def test_parse_master_index_keeps_only_8k_candidates():
    collector = SecCollector()

    rows = collector._parse_master_index(MASTER_INDEX)

    assert [row["form"] for row in rows] == ["8-K", "8-K/A", "8-K"]
    assert rows[0]["cik"] == "0000320193"
    assert rows[0]["accession"] == "0000320193-26-000101"
    assert all(row["form"] != "10-Q" for row in rows)


def test_parse_master_index_accepts_real_edgar_header():
    # Regression: EDGAR's live header is "...|File Name" (with a space).
    # The parser originally waited for "Filename", never matched, and
    # silently returned zero candidates from every live daily index.
    collector = SecCollector()

    rows = collector._parse_master_index(MASTER_INDEX)

    assert len(rows) == 3


def test_load_company_tickers_builds_cik_map(monkeypatch):
    collector = SecCollector(request_interval=0)

    class MockResponse:
        status_code = 200

        def json(self):
            return COMPANY_TICKERS

    monkeypatch.setattr(collector.session, "get", lambda *args, **kwargs: MockResponse())

    mapping = collector._load_company_tickers()

    assert mapping["0000320193"] == ("AAPL", "Apple Inc.")
    assert mapping["0001652044"] == ("GOOGL", "Alphabet Inc.")


def test_discovery_skips_missing_index_and_dedupes_accessions(monkeypatch):
    collector = SecCollector(request_interval=0)
    called_urls: list[str] = []

    class MockResponse:
        def __init__(self, status_code=200, text="", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload

        def json(self):
            return self._payload

    def mock_get(url, timeout=10):
        called_urls.append(url)
        if url.endswith("company_tickers.json"):
            return MockResponse(payload=COMPANY_TICKERS)
        if "master.20261101.idx" in url:
            return MockResponse(status_code=404)
        if "master.20261102.idx" in url:
            return MockResponse(text=MASTER_INDEX)
        if "master.20261103.idx" in url:
            return MockResponse(text=MASTER_INDEX)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(collector.session, "get", mock_get)

    candidates = collector._discover_candidates(
        since=datetime(2026, 11, 1),
        today=date(2026, 11, 3),
    )

    assert len(candidates) == 3
    assert {c["accession"] for c in candidates} == {
        "0000320193-26-000101",
        "0000320193-26-000102",
        "0001652044-26-000777",
    }
    assert candidates[0]["ticker"] in {"AAPL", "GOOGL"}
    assert any("master.20261101.idx" in url for url in called_urls)


def test_sec_collector_auto_discovers_without_sec_ciks(monkeypatch):
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    collector = SecCollector(request_interval=0)

    monkeypatch.delenv("SEC_CIKS", raising=False)
    monkeypatch.setattr(
        collector,
        "_discover_candidates",
        lambda since, today=None: [
            {
                "cik": "0000320193",
                "company": "Apple Inc.",
                "ticker": "AAPL",
                "form": "8-K",
                "filing_date": "2026-10-31",
                "filename": "edgar/data/320193/0000320193-26-000101.txt",
                "accession": "0000320193-26-000101",
            },
            {
                "cik": "0000320193",
                "company": "Apple Inc.",
                "ticker": "AAPL",
                "form": "8-K",
                "filing_date": "2026-10-25",
                "filename": "edgar/data/320193/0000320193-26-000102.txt",
                "accession": "0000320193-26-000102",
            },
        ],
    )

    class MockResponse:
        status_code = 200

        def json(self):
            return payload

    monkeypatch.setattr(collector.session, "get", lambda *args, **kwargs: MockResponse())

    events = collector.collect(since=datetime(2026, 10, 1))

    assert len(events) == 2
    assert {e.event_type for e in events} == {"EARNINGS", "STOCK_SPLIT"}


def test_unrelated_8k_is_ignored(monkeypatch):
    payload = {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-009999"],
                "filingDate": ["2026-11-03"],
                "acceptanceDateTime": ["2026-11-03T12:00:00.000Z"],
                "form": ["8-K"],
                "items": ["Item 5.02"],
                "primaryDocument": ["officer-change.htm"],
                "primaryDocDescription": ["Departure of Directors or Certain Officers"],
            }
        },
    }
    collector = SecCollector(request_interval=0)
    monkeypatch.setattr(
        collector,
        "_discover_candidates",
        lambda since, today=None: [{
            "cik": "0000320193",
            "company": "Apple Inc.",
            "ticker": "AAPL",
            "form": "8-K",
            "filing_date": "2026-11-03",
            "filename": "edgar/data/320193/0000320193-26-009999.txt",
            "accession": "0000320193-26-009999",
        }],
    )

    class MockResponse:
        status_code = 200

        def json(self):
            return payload

    monkeypatch.setattr(collector.session, "get", lambda *args, **kwargs: MockResponse())

    assert collector.collect(since=datetime(2026, 11, 1)) == []


def test_one_enrichment_failure_does_not_discard_other_company(monkeypatch):
    apple_payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    collector = SecCollector(request_interval=0)
    monkeypatch.setattr(
        collector,
        "_discover_candidates",
        lambda since, today=None: [
            {
                "cik": "0000320193",
                "company": "Apple Inc.",
                "ticker": "AAPL",
                "form": "8-K",
                "filing_date": "2026-10-31",
                "filename": "edgar/data/320193/0000320193-26-000101.txt",
                "accession": "0000320193-26-000101",
            },
            {
                "cik": "0001652044",
                "company": "Alphabet Inc.",
                "ticker": "GOOGL",
                "form": "8-K",
                "filing_date": "2026-11-03",
                "filename": "edgar/data/1652044/0001652044-26-000777.txt",
                "accession": "0001652044-26-000777",
            },
        ],
    )

    class MockResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def mock_get(url, timeout=10):
        if "CIK0000320193.json" in url:
            return MockResponse(200, apple_payload)
        if "CIK0001652044.json" in url:
            return MockResponse(500)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(collector.session, "get", mock_get)

    events = collector.collect(since=datetime(2026, 10, 1))

    assert len(events) == 1
    assert events[0].primary_ticker == "AAPL"
    assert events[0].event_type == "EARNINGS"


MASTER_INDEX_WITH_SMALLCAP = """Description: Master Index of EDGAR Dissemination Feed
CIK|Company Name|Form Type|Date Filed|File Name
320193|Apple Inc.|8-K|2026-11-03|edgar/data/320193/0000320193-26-000101.txt
320193|Apple Inc.|8-K/A|2026-11-03|edgar/data/320193/0000320193-26-000102.txt
1652044|Alphabet Inc.|8-K|2026-11-03|edgar/data/1652044/0001652044-26-000777.txt
9999999|Tiny Corp|8-K|2026-11-03|edgar/data/9999999/0009999999-26-000001.txt
"""

TICKERS_WITH_SMALLCAP = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
    "2": {"cik_str": 9999999, "ticker": "TINY", "title": "Tiny Corp"},
}


def _mock_index_and_tickers(monkeypatch, collector, index_text, tickers):
    class MockResponse:
        def __init__(self, status_code=200, text="", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload

        def json(self):
            return self._payload

    def mock_get(url, timeout=10):
        if url.endswith("company_tickers.json"):
            return MockResponse(payload=tickers)
        if "master." in url and url.endswith(".idx"):
            return MockResponse(text=index_text)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(collector.session, "get", mock_get)


def test_discovery_filters_out_non_large_cap_companies(monkeypatch):
    collector = SecCollector(request_interval=0, universe_tickers={"AAPL", "GOOGL"})
    _mock_index_and_tickers(
        monkeypatch, collector, MASTER_INDEX_WITH_SMALLCAP, TICKERS_WITH_SMALLCAP
    )

    candidates = collector._discover_candidates(
        since=datetime(2026, 11, 1),
        today=date(2026, 11, 3),
    )

    assert {c["ticker"] for c in candidates} == {"AAPL", "GOOGL"}
    assert all(c["cik"] != "0009999999" for c in candidates)


def test_discovery_without_universe_keeps_all_candidates(monkeypatch, tmp_path):
    # Fail-open: an unavailable universe file must not zero out collection.
    collector = SecCollector(
        request_interval=0,
        universe_path=tmp_path / "missing-universe.json",
    )
    _mock_index_and_tickers(
        monkeypatch, collector, MASTER_INDEX_WITH_SMALLCAP, TICKERS_WITH_SMALLCAP
    )

    candidates = collector._discover_candidates(
        since=datetime(2026, 11, 1),
        today=date(2026, 11, 3),
    )

    assert {c["ticker"] for c in candidates} == {"AAPL", "GOOGL", "TINY"}


def test_collect_never_fetches_submissions_for_filtered_companies(monkeypatch):
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    collector = SecCollector(request_interval=0, universe_tickers={"AAPL"})
    fetched_urls: list[str] = []

    class MockResponse:
        def __init__(self, status_code=200, text="", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload

        def json(self):
            return self._payload

    def mock_get(url, timeout=10):
        fetched_urls.append(url)
        if url.endswith("company_tickers.json"):
            return MockResponse(payload=TICKERS_WITH_SMALLCAP)
        if "master." in url and url.endswith(".idx"):
            return MockResponse(text=MASTER_INDEX_WITH_SMALLCAP)
        if "CIK0000320193.json" in url:
            return MockResponse(payload=payload)
        raise AssertionError(f"submissions fetched for filtered company: {url}")

    monkeypatch.setattr(collector.session, "get", mock_get)

    events = collector.collect(since=datetime(2026, 10, 1))

    assert len(events) == 2
    assert {e.primary_ticker for e in events} == {"AAPL"}
    assert not any("9999999" in url or "1652044" in url for url in fetched_urls)


def test_sec_collector_graceful_on_discovery_error(monkeypatch):
    collector = SecCollector(request_interval=0)

    def fail_discovery(*args, **kwargs):
        raise ConnectionError("SEC EDGAR down")

    monkeypatch.setattr(collector, "_discover_candidates", fail_discovery)

    assert collector.collect(since=datetime(2026, 10, 1)) == []
