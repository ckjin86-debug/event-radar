import json
from datetime import date, datetime

from event_radar.models import Event
from event_radar.pipeline import prune_non_large_cap_sec_events
from event_radar.sec_universe import load_large_cap_universe, normalize_us_ticker


def _event(event_id: str, source_name: str, ticker: str) -> Event:
    now = datetime(2026, 11, 3, 10, 0, 0)
    return Event(
        event_id=event_id,
        country="US",
        event_type="EARNINGS",
        event_name=f"{ticker} earnings",
        primary_ticker=ticker,
        primary_company="Test Corp",
        announced_at=now,
        event_date=date(2026, 11, 3),
        event_time_context="DATE_ONLY",
        status="CONFIRMED",
        source_kind="REGULATOR",
        source_name=source_name,
        source_url="https://example.com",
        source_event_uid=event_id,
        evidence_text="8-K Item 2.02",
        ingest_mode="AUTO",
        first_seen_at=now,
        last_seen_at=now,
        needs_review=False,
    )


def test_normalize_us_ticker_matches_sec_style():
    assert normalize_us_ticker("brk.b") == "BRK-B"
    assert normalize_us_ticker(" AAPL ") == "AAPL"
    assert normalize_us_ticker("BF.B") == "BF-B"
    assert normalize_us_ticker("") == ""


def test_load_large_cap_universe_reads_and_normalizes(tmp_path):
    path = tmp_path / "universe.json"
    path.write_text(
        json.dumps({"tickers": ["AAPL", "brk.b", "MSFT"]}),
        encoding="utf-8",
    )

    universe = load_large_cap_universe(path)

    assert universe == frozenset({"AAPL", "BRK-B", "MSFT"})


def test_load_large_cap_universe_missing_or_bad_file_is_none(tmp_path):
    assert load_large_cap_universe(tmp_path / "missing.json") is None

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_large_cap_universe(bad) is None

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"tickers": []}), encoding="utf-8")
    assert load_large_cap_universe(empty) is None


def test_prune_drops_only_non_large_cap_sec_8k_events():
    universe = frozenset({"AAPL", "BRK-B"})
    events = [
        _event("sec-large", "SEC", "AAPL"),
        _event("sec-class-share", "SEC", "BRK-B"),
        _event("sec-small", "SEC", "TINY"),
        _event("sec-13dg-small", "SEC_13DG", "TINY"),
        _event("news-small", "NEWS_FUTURE", "TINY"),
    ]

    kept = prune_non_large_cap_sec_events(events, universe)

    assert [ev.event_id for ev in kept] == [
        "sec-large",
        "sec-class-share",
        "sec-13dg-small",
        "news-small",
    ]


def test_prune_without_universe_keeps_everything():
    events = [_event("sec-small", "SEC", "TINY")]

    assert prune_non_large_cap_sec_events(events, None) == events
