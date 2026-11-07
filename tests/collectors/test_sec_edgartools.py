"""Pilot tests for the edgartools-based SEC 8-K collector variant.

The conversion tests are skipped when the optional ``edgartools``
package is not installed, so the production test suite is unaffected by
this pilot. The header-drift tests document *why* the pilot exists:
they pin down the production master-index parser's silent-zero failure
modes and the edgartools index reader's different behaviour.
"""

from datetime import date, datetime, timezone

import pytest

from event_radar.collectors import sec_edgartools
from event_radar.collectors.sec import SecCollector
from event_radar.collectors.sec_edgartools import SecEdgartoolsCollector


SINCE = datetime(2026, 10, 26)


def test_collect_without_edgartools_fails_soft(monkeypatch):
    # The pilot collector must never raise into the pipeline when the
    # optional dependency is missing; it logs FAILED and returns [].
    monkeypatch.setattr(sec_edgartools, "_edgar", None)
    collector = SecEdgartoolsCollector(tickers=["AAPL"])
    assert collector.collect(SINCE) == []


def _row(**overrides):
    row = {
        "form": "8-K",
        "items": "2.02,9.01",
        "primaryDocDescription": "",
        "filing_date": date(2026, 11, 2),
        "acceptanceDateTime": datetime(2026, 11, 2, 21, 30, 23, tzinfo=timezone.utc),
        "accession_number": "0000320193-26-000024",
        "primaryDocument": "aapl-20261102.htm",
    }
    row.update(overrides)
    return row


@pytest.mark.skipif(sec_edgartools._edgar is None, reason="edgartools not installed")
def test_row_to_event_earnings_afterhours():
    collector = SecEdgartoolsCollector()
    event = collector._row_to_event(
        _row(), cik="320193", company_name="Apple Inc.", primary_ticker="AAPL", since=SINCE
    )
    assert event is not None
    assert event.event_type == "EARNINGS"
    assert event.event_time_context == "AFTERHOURS"
    assert event.source_event_uid == "0000320193-26-000024"
    assert event.event_date == date(2026, 11, 2)
    assert event.primary_ticker == "AAPL"
    assert event.source_url.endswith("/000032019326000024/aapl-20261102.htm")


@pytest.mark.skipif(sec_edgartools._edgar is None, reason="edgartools not installed")
def test_row_to_event_split_date_from_description():
    collector = SecEdgartoolsCollector()
    event = collector._row_to_event(
        _row(items="3.03", primaryDocDescription="Split effective 2026-11-20"),
        cik="320193",
        company_name="Apple Inc.",
        primary_ticker="AAPL",
        since=SINCE,
    )
    assert event is not None
    assert event.event_type == "STOCK_SPLIT"
    assert event.event_date == date(2026, 11, 20)


@pytest.mark.skipif(sec_edgartools._edgar is None, reason="edgartools not installed")
def test_row_to_event_string_acceptance_and_unclassifiable():
    collector = SecEdgartoolsCollector()
    event = collector._row_to_event(
        _row(acceptanceDateTime="2026-11-02T08:05:00.000Z"),
        cik="320193",
        company_name="Apple Inc.",
        primary_ticker="AAPL",
        since=SINCE,
    )
    assert event is not None
    assert event.event_time_context == "PREMARKET"

    # Item 5.02 (officer departure) is not one of the production event
    # types, and non-8-K forms are out of scope: both convert to None,
    # exactly as the production collector behaves.
    assert (
        collector._row_to_event(
            _row(items="5.02"),
            cik="320193",
            company_name="Apple Inc.",
            primary_ticker="AAPL",
            since=SINCE,
        )
        is None
    )
    assert (
        collector._row_to_event(
            _row(form="10-Q"),
            cik="320193",
            company_name="Apple Inc.",
            primary_ticker="AAPL",
            since=SINCE,
        )
        is None
    )


# ----------------------------------------------------------------------
# Fragility documentation: why the pilot exists.
# ----------------------------------------------------------------------

MASTER_SAMPLE_ROWS = [
    "320193|Apple Inc.|8-K|2026-11-03|edgar/data/320193/0000320193-26-000101.txt",
    "1652044|Alphabet Inc.|8-K|2026-11-03|edgar/data/1652044/0001652044-26-000777.txt",
]


def _master_text(header: str) -> str:
    return "Description: Master Index\n" + header + "\n" + "\n".join(MASTER_SAMPLE_ROWS) + "\n"


def test_production_parser_silently_empty_on_header_drift():
    # The production discovery gate is a literal, case-sensitive header
    # prefix match. Plausible EDGAR header drifts yield *zero rows with
    # no error* — the failure mode behind the historical SEC outage.
    collector = SecCollector()
    assert len(collector._parse_master_index(_master_text("CIK|Company Name|Form Type|Date Filed|File Name"))) == 2
    assert collector._parse_master_index(_master_text("cik|company name|form type|date filed|file name")) == []
    assert collector._parse_master_index(_master_text("CIK | Company Name | Form Type | Date Filed | File Name")) == []


FORM_INDEX_SAMPLE = """Description:           Daily Index of EDGAR Dissemination Feed
Last Data Received:    Nov 5, 2026
Comments:              webmaster@sec.gov

{header}
--------------------------------------------------------------------------------
8-K            Apple Inc.              320193    20261103  edgar/data/320193/0000320193-26-000101.txt
10-Q           Microsoft Corp          789019    20261103  edgar/data/789019/0000789019-26-000999.txt
"""


def test_edgartools_index_reader_ignores_header_text():
    pytest.importorskip("edgar")
    from edgar._filings import read_index_file

    def accessions(text: str) -> list[str]:
        table = read_index_file(text, form_column=0, filing_date_format="%Y%m%d")
        return [str(a) for a in table.column("accession_number").to_pylist()]

    control = accessions(FORM_INDEX_SAMPLE.format(header="Form Type  Company Name  CIK  Date Filed  File Name"))
    replaced = accessions(FORM_INDEX_SAMPLE.format(header="COMPLETELY DIFFERENT WORDING"))
    assert control == replaced == ["0000320193-26-000101", "0000789019-26-000999"]

    # Removing the dashed separator is the one drift that breaks it —
    # but it raises (loud) instead of silently returning zero rows.
    no_separator = FORM_INDEX_SAMPLE.format(header="H").replace(
        "--------------------------------------------------------------------------------\n", ""
    )
    with pytest.raises(Exception):
        accessions(no_separator)
