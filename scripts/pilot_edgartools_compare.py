"""Pilot comparison: production SEC parsing vs edgartools (branch pilot).

Part A — parsing parity (live, per ticker):
    Baseline: live data.sec.gov submissions JSON fed into the production
    ``SecCollector._events_from_payload``.
    Pilot:    ``SecEdgartoolsCollector.events_for_ticker``.
    Compares accession sets and, per shared accession, event_type,
    event_date, time context and event name.

Part B — discovery parity (live, one day):
    Baseline: production ``_parse_master_index`` over the day's EDGAR
    master index text.
    Pilot:    ``SecEdgartoolsCollector.discover_day`` (edgartools daily
    form index). Compares 8-K accession sets, both raw and restricted to
    the large-cap universe CIKs the production collector would keep.

Part C — fragility (offline):
    Header/format variants of a master-index text are fed to (i) the
    production parser and (ii) edgartools' ``read_pipe_delimited_index``,
    plus the edgartools parser is run over the real master text fetched
    in Part B. The historical incident class — a literal header-string
    drift silently yielding zero rows — is what is being probed.

Usage (pilot venv):
    python scripts/pilot_edgartools_compare.py \
        --tickers AAPL,MSFT,NVDA,GOOGL --since 2026-10-26 --day 2026-11-05

Network use is deliberately small: one company_tickers.json, one
submissions JSON per ticker, one daily master index, plus whatever
edgartools fetches for the same scope. SEC fair-access pacing is kept.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from event_radar.collectors.sec import (  # noqa: E402
    SEC_DEFAULT_USER_AGENT,
    SEC_SUBMISSIONS_URL,
    SecCollector,
)
from event_radar.collectors.sec_edgartools import SecEdgartoolsCollector  # noqa: E402

REQUEST_PAUSE_SEC = 0.35


def _get_json(session: requests.Session, url: str) -> dict:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    time.sleep(REQUEST_PAUSE_SEC)
    return response.json()


def _get_text(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    time.sleep(REQUEST_PAUSE_SEC)
    return response.text


def event_fingerprint(event) -> dict:
    return {
        "event_type": event.event_type,
        "event_date": event.event_date.isoformat() if event.event_date else None,
        "time_context": event.event_time_context,
        "event_name": event.event_name,
        "primary_ticker": event.primary_ticker,
    }


def part_a(tickers: list[str], since: datetime) -> dict:
    session = requests.Session()
    session.headers.update({"User-Agent": SEC_DEFAULT_USER_AGENT})

    baseline_collector = SecCollector(request_interval=0)
    ticker_map = baseline_collector._load_company_tickers()
    cik_by_ticker = {ticker: cik for cik, (ticker, _t) in ticker_map.items()}

    pilot = SecEdgartoolsCollector(tickers=tickers)
    results: dict = {}
    for ticker in tickers:
        cik = cik_by_ticker.get(ticker)
        if cik is None:
            results[ticker] = {"error": "ticker not in SEC company map"}
            continue

        payload = _get_json(session, SEC_SUBMISSIONS_URL.format(cik=cik))
        baseline_events = baseline_collector._events_from_payload(payload, since=since)
        pilot_events = pilot.events_for_ticker(ticker, since)

        baseline_by_acc = {e.source_event_uid: e for e in baseline_events}
        pilot_by_acc = {e.source_event_uid: e for e in pilot_events}
        shared = sorted(set(baseline_by_acc) & set(pilot_by_acc))
        mismatches = []
        for accession in shared:
            b = event_fingerprint(baseline_by_acc[accession])
            p = event_fingerprint(pilot_by_acc[accession])
            if b != p:
                mismatches.append({"accession": accession, "baseline": b, "pilot": p})

        results[ticker] = {
            "baseline_count": len(baseline_events),
            "pilot_count": len(pilot_events),
            "baseline_only": sorted(set(baseline_by_acc) - set(pilot_by_acc)),
            "pilot_only": sorted(set(pilot_by_acc) - set(baseline_by_acc)),
            "shared": len(shared),
            "field_mismatches": mismatches,
        }
    return results


def part_b(day: date, since: datetime) -> dict:
    session = requests.Session()
    session.headers.update({"User-Agent": SEC_DEFAULT_USER_AGENT})

    baseline_collector = SecCollector(request_interval=0)
    index_text = _get_text(session, baseline_collector._daily_index_url(day))
    preamble = index_text.splitlines()[:12]
    quarter = ((day.month - 1) // 3) + 1
    form_index_url = (
        "https://www.sec.gov/Archives/edgar/daily-index/"
        f"{day.year}/QTR{quarter}/form.{day.strftime('%Y%m%d')}.idx"
    )
    form_text = _get_text(session, form_index_url)

    baseline_rows = baseline_collector._parse_master_index(index_text)
    baseline_acc = {row["accession"] for row in baseline_rows}

    pilot = SecEdgartoolsCollector()
    pilot_rows = pilot.discover_day(day)
    pilot_acc = {
        str(row.get("accession_number"))
        for row in pilot_rows
        if row.get("accession_number")
    }
    pilot_cik_missing = sum(1 for row in pilot_rows if not row.get("cik"))

    # Large-cap restricted comparison (what production would actually keep).
    ticker_map = baseline_collector._load_company_tickers()
    large_cap_ciks = baseline_collector._large_cap_ciks(ticker_map)
    if large_cap_ciks is not None:
        baseline_lc = {
            row["accession"] for row in baseline_rows if row["cik"] in large_cap_ciks
        }
        pilot_lc = {
            str(row.get("accession_number"))
            for row in pilot_rows
            if str(row.get("cik") or "").zfill(10) in large_cap_ciks
        }
    else:
        baseline_lc = pilot_lc = None

    # edgartools' own pipe-delimited master parser over the *same* text the
    # production parser just consumed — the direct fragility cross-check.
    edgar_parser_acc: set[str] | None = None
    edgar_parser_error: str | None = None
    try:
        from edgar._filings import read_pipe_delimited_index

        table = read_pipe_delimited_index(index_text)
        edgar_parser_acc = {
            str(acc) for acc in table.column("accession_number").to_pylist()
        }
        # read_pipe_delimited_index returns every form; keep the 8-K family.
        forms = table.column("form").to_pylist()
        accs = table.column("accession_number").to_pylist()
        edgar_parser_acc = {
            str(acc)
            for acc, form in zip(accs, forms)
            if str(form).upper() in {"8-K", "8-K/A"}
        }
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        edgar_parser_error = f"{type(exc).__name__}: {exc}"

    return {
        "day": day.isoformat(),
        "master_index_preamble_first_12_lines": preamble,
        "baseline_rows": len(baseline_rows),
        "pilot_rows": len(pilot_rows),
        "pilot_rows_missing_cik": pilot_cik_missing,
        "baseline_only_count": len(baseline_acc - pilot_acc),
        "pilot_only_count": len(pilot_acc - baseline_acc),
        "baseline_only_sample": sorted(baseline_acc - pilot_acc)[:10],
        "pilot_only_sample": sorted(pilot_acc - baseline_acc)[:10],
        "large_cap": (
            None
            if baseline_lc is None
            else {
                "baseline_count": len(baseline_lc),
                "pilot_count": len(pilot_lc),
                "baseline_only": sorted(baseline_lc - pilot_lc)[:10],
                "pilot_only": sorted(pilot_lc - baseline_lc)[:10],
            }
        ),
        "edgartools_pipe_parser_on_same_master_text": (
            {"error": edgar_parser_error}
            if edgar_parser_acc is None
            else {
                "rows_8k": len(edgar_parser_acc),
                "matches_baseline_8k_set": edgar_parser_acc == baseline_acc,
                "baseline_only_count": len(baseline_acc - edgar_parser_acc),
                "parser_only_count": len(edgar_parser_acc - baseline_acc),
            }
        ),
        "_master_text": index_text,
        "_form_text": form_text,
    }


SAMPLE_ROWS = [
    "320193|Apple Inc.|8-K|2026-11-03|edgar/data/320193/0000320193-26-000101.txt",
    "320193|Apple Inc.|8-K/A|2026-11-03|edgar/data/320193/0000320193-26-000102.txt",
    "1652044|Alphabet Inc.|8-K|2026-11-03|edgar/data/1652044/0001652044-26-000777.txt",
]
REAL_HEADER = "CIK|Company Name|Form Type|Date Filed|File Name"


def _variant_texts() -> dict[str, str]:
    def build(header: str, rows: list[str], prefix: str = "Description: Master Index\n") -> str:
        return prefix + header + "\n" + "\n".join(rows) + "\n"

    swapped_rows = [
        "320193|Apple Inc.|2026-11-03|8-K|edgar/data/320193/0000320193-26-000101.txt",
        "320193|Apple Inc.|2026-11-03|8-K/A|edgar/data/320193/0000320193-26-000102.txt",
        "1652044|Alphabet Inc.|2026-11-03|8-K|edgar/data/1652044/0001652044-26-000777.txt",
    ]
    return {
        "control_real_header": build(REAL_HEADER, SAMPLE_ROWS),
        "filename_no_space (historic bug)": build(
            "CIK|Company Name|Form Type|Date Filed|Filename", SAMPLE_ROWS
        ),
        "lowercase_header": build(
            "cik|company name|form type|date filed|file name", SAMPLE_ROWS
        ),
        "bom_before_header": build(REAL_HEADER, SAMPLE_ROWS, prefix="Description: Master Index\n﻿"),
        "crlf_line_endings": build(REAL_HEADER, SAMPLE_ROWS).replace("\n", "\r\n"),
        "spaced_pipes_header": build(
            "CIK | Company Name | Form Type | Date Filed | File Name", SAMPLE_ROWS
        ),
        "extra_preamble_lines": build(
            REAL_HEADER,
            SAMPLE_ROWS,
            prefix="Description: Master Index\nExtra: new preamble line A\nExtra: new preamble line B\n",
        ),
        "swapped_form_date_columns": build(
            "CIK|Company Name|Date Filed|Form Type|File Name", swapped_rows
        ),
    }


FORM_INDEX_SAMPLE = """Description:           Daily Index of EDGAR Dissemination Feed
Last Data Received:    Nov 5, 2026
Comments:              webmaster@sec.gov
Anonymous FTP:         ftp://ftp.sec.gov/edgar/

HEADERLINE
--------------------------------------------------------------------------------
8-K            Apple Inc.              320193    20261103  edgar/data/320193/0000320193-26-000101.txt
8-K/A          Apple Inc.              320193    20261103  edgar/data/320193/0000320193-26-000102.txt
8-K            Alphabet Inc.           1652044   20261103  edgar/data/1652044/0001652044-26-000777.txt
10-Q           Microsoft Corp          789019    20261103  edgar/data/789019/0000789019-26-000999.txt
"""


def _form_index_variants() -> dict[str, str]:
    """Variants of a daily *form* index text — the file edgartools'
    discover path actually parses (via read_index_file, which locates
    data after the dashed separator line and never reads header text)."""
    control = FORM_INDEX_SAMPLE.replace(
        "HEADERLINE", "Form Type        Company Name          CIK       Date Filed  File Name"
    )
    return {
        "control": control,
        "header_text_replaced": FORM_INDEX_SAMPLE.replace(
            "HEADERLINE", "COMPLETELY DIFFERENT WORDING HERE"
        ),
        "header_line_removed": FORM_INDEX_SAMPLE.replace("HEADERLINE\n", ""),
        "separator_line_removed": control.replace(
            "--------------------------------------------------------------------------------\n", ""
        ),
        "extra_preamble_lines": control.replace(
            "Anonymous FTP:         ftp://ftp.sec.gov/edgar/\n",
            "Anonymous FTP:         ftp://ftp.sec.gov/edgar/\nExtra preamble line A\nExtra preamble line B\n",
        ),
    }


def part_c(form_text: str = "") -> dict:
    baseline_collector = SecCollector(request_interval=0)
    production_results: dict[str, int] = {}
    for name, text in _variant_texts().items():
        production_results[name] = len(baseline_collector._parse_master_index(text))

    # edgartools discovery-path parser (read_index_file) on form-index
    # variants: header wording is never consulted, so the question is
    # whether each drift yields the same rows, different rows, or a loud
    # exception (vs the production parser's silent zero).
    edgartools_results: dict[str, object] = {}
    try:
        from edgar._filings import read_index_file

        for name, text in _form_index_variants().items():
            try:
                table = read_index_file(text, form_column=0, filing_date_format="%Y%m%d")
                forms = [str(f) for f in table.column("form").to_pylist()]
                accs = [str(a) for a in table.column("accession_number").to_pylist()]
                edgartools_results[name] = {
                    "rows": table.num_rows,
                    "forms": forms,
                    "accessions": accs,
                }
            except Exception as exc:  # noqa: BLE001
                edgartools_results[name] = {"error": f"{type(exc).__name__}: {exc}"}

        if form_text:
            try:
                table = read_index_file(
                    form_text, form_column=0, filing_date_format="%Y%m%d"
                )
                accs = {
                    str(a) for a in table.column("accession_number").to_pylist()
                }
                forms = [str(f) for f in table.column("form").to_pylist()]
                edgartools_results["real_form_index_text"] = {
                    "rows": table.num_rows,
                    "rows_8k_family": sum(
                        1 for f in forms if f.upper() in {"8-K", "8-K/A"}
                    ),
                    "unique_accessions": len(accs),
                }
            except Exception as exc:  # noqa: BLE001
                edgartools_results["real_form_index_text"] = {
                    "error": f"{type(exc).__name__}: {exc}"
                }
    except Exception as exc:  # noqa: BLE001
        edgartools_results["import"] = {"error": f"{type(exc).__name__}: {exc}"}

    return {
        "production_parse_master_index_row_counts": production_results,
        "edgartools_read_index_file_on_form_index": edgartools_results,
        "note": (
            "Production counts are 8-K rows kept from 3 sample rows. "
            "edgartools counts cover all rows of the sample form index "
            "(3x 8-K family + 1x 10-Q)."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default="AAPL,MSFT,NVDA,GOOGL")
    parser.add_argument("--since", default="2026-10-26")
    parser.add_argument("--day", default="2026-11-05")
    parser.add_argument("--skip-a", action="store_true")
    parser.add_argument("--skip-b", action="store_true")
    parser.add_argument("--skip-c", action="store_true")
    args = parser.parse_args()

    since = datetime.fromisoformat(args.since)
    day = date.fromisoformat(args.day)
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    report: dict = {}
    form_text = ""
    if not args.skip_a:
        report["part_a_parsing_parity"] = part_a(tickers, since)
    if not args.skip_b:
        part_b_result = part_b(day, since)
        master_text = part_b_result.pop("_master_text")
        form_text = part_b_result.pop("_form_text")
        report["part_b_discovery_parity"] = part_b_result
        out = Path("/tmp/pilot_master_index_sample.txt")
        out.write_text(master_text, encoding="utf-8")
        Path("/tmp/pilot_form_index_sample.txt").write_text(form_text, encoding="utf-8")
        report["part_b_master_text_saved_to"] = str(out)
    if not args.skip_c:
        report["part_c_fragility"] = part_c(form_text)

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
