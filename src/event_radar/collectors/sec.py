"""SEC EDGAR collector for US corporate actions, earnings 8-Ks, and splits."""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from event_radar.collectors.base import CollectorRunLog, log_collector_run
from event_radar.models import RawEvent
from event_radar.sec_universe import load_large_cap_universe, normalize_us_ticker


SEC_DEFAULT_USER_AGENT = "EventRadarAdmin admin@eventradar.org"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_DAILY_INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/daily-index/"
    "{year}/QTR{quarter}/master.{yyyymmdd}.idx"
)
SEC_DISCOVERY_DAYS = 3
TARGET_FORMS = {"8-K", "8-K/A"}


class SecCollector:
    """Collector for US corporate filings discovered from SEC EDGAR indexes."""

    source_name: str = "SEC"

    def __init__(
        self,
        fixture_path: Optional[Path | str] = None,
        user_agent: str = SEC_DEFAULT_USER_AGENT,
        timeout: int = 20,
        request_interval: float = 0.12,
        max_workers: int = 5,
        universe_path: Optional[Path | str] = None,
        universe_tickers: Optional[set[str]] = None,
    ):
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.timeout = timeout
        self.request_interval = max(0.0, request_interval)
        self.max_workers = max(1, max_workers)
        self._last_request_at = 0.0
        self._rate_lock = threading.Lock()
        self._ticker_map_cache: Optional[dict[str, tuple[str, str]]] = None
        # Large-cap policy: only S&P 500 / Nasdaq-100 constituents' 8-Ks are
        # collected. An explicit ticker set wins (tests); otherwise the
        # universe JSON is loaded lazily. A missing file disables filtering
        # (fail-open) instead of silently collecting nothing.
        self._universe_path = Path(universe_path) if universe_path else None
        self._universe_tickers: Optional[frozenset[str]] = (
            frozenset(normalize_us_ticker(t) for t in universe_tickers)
            if universe_tickers is not None
            else None
        )
        self._universe_loaded = universe_tickers is not None

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )

    def _get(self, url: str):
        """Rate-limit SEC requests while keeping network access mockable in tests."""
        with self._rate_lock:
            if self.request_interval > 0 and self._last_request_at:
                elapsed = time.monotonic() - self._last_request_at
                remaining = self.request_interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
            self._last_request_at = time.monotonic()

        return self.session.get(url, timeout=self.timeout)

    def _determine_event_type(self, form: str, items: str, desc: str) -> Optional[str]:
        combined = f"{form} {items} {desc}".upper()
        if "2.02" in items or "EARNINGS" in combined:
            return "EARNINGS"
        if "3.03" in items or "SPLIT" in combined:
            return "STOCK_SPLIT"
        if "OFFERING" in combined or "3.02" in items:
            return "RIGHTS_ISSUE"
        return None

    def _determine_time_context(self, accept_str: str) -> str:
        try:
            if "T" in accept_str:
                time_part = accept_str.split("T")[1][:5]
                hh, mm = map(int, time_part.split(":"))
                if hh >= 16 or (hh == 16 and mm > 0):
                    return "AFTERHOURS"
                if hh < 9 or (hh == 9 and mm < 30):
                    return "PREMARKET"
                return "INTRADAY"
        except Exception:
            pass
        return "DATE_ONLY"

    def _extract_date(self, text: str, default_date: date) -> date:
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass
        return default_date

    def _parse_master_index(self, text: str) -> list[dict]:
        """Parse a SEC daily master index and return only 8-K candidates."""
        rows: list[dict] = []
        header_seen = False

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not header_seen:
                # EDGAR's real header ends with "File Name" (with a space);
                # the original code waited for "Filename", never matched,
                # and silently parsed zero rows from every live index.
                if line.startswith("CIK|Company Name|Form Type|Date Filed|File"):
                    header_seen = True
                continue
            if not line or "|" not in line:
                continue

            parts = line.split("|", 4)
            if len(parts) != 5:
                continue

            cik, company, form, filing_date, filename = [part.strip() for part in parts]
            form = form.upper()
            if form not in TARGET_FORMS:
                continue

            accession = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            if not accession:
                continue

            rows.append(
                {
                    "cik": str(cik).zfill(10),
                    "company": company,
                    "form": form,
                    "filing_date": filing_date,
                    "filename": filename,
                    "accession": accession,
                }
            )

        return rows

    def _load_company_tickers(self) -> dict[str, tuple[str, str]]:
        """Load SEC CIK -> (ticker, company) mapping once per collector run."""
        if self._ticker_map_cache is not None:
            return self._ticker_map_cache

        response = self._get(SEC_COMPANY_TICKERS_URL)
        if response.status_code != 200:
            raise ConnectionError(f"SEC company ticker map HTTP {response.status_code}")

        payload = response.json()
        mapping: dict[str, tuple[str, str]] = {}
        records = payload.values() if isinstance(payload, dict) else payload
        for record in records:
            if not isinstance(record, dict):
                continue
            cik = str(record.get("cik_str", "")).strip()
            ticker = str(record.get("ticker", "")).strip().upper()
            title = str(record.get("title", "")).strip()
            if not cik or not ticker:
                continue
            mapping.setdefault(cik.zfill(10), (ticker, title))

        self._ticker_map_cache = mapping
        return mapping

    def _large_cap_tickers(self) -> Optional[frozenset[str]]:
        """Return the large-cap universe tickers, or None to skip filtering."""
        if not self._universe_loaded:
            self._universe_tickers = load_large_cap_universe(self._universe_path)
            self._universe_loaded = True
        return self._universe_tickers

    def _large_cap_ciks(
        self,
        ticker_map: dict[str, tuple[str, str]],
    ) -> Optional[set[str]]:
        """Resolve universe tickers to CIKs via the SEC company ticker map.

        Returns None when filtering cannot apply (universe unavailable or
        the ticker map failed to load), so discovery stays fail-open.
        """
        universe = self._large_cap_tickers()
        if universe is None or not ticker_map:
            return None
        return {
            cik
            for cik, (ticker, _title) in ticker_map.items()
            if normalize_us_ticker(ticker) in universe
        }

    def _daily_index_url(self, day: date) -> str:
        quarter = ((day.month - 1) // 3) + 1
        return SEC_DAILY_INDEX_URL.format(
            year=day.year,
            quarter=quarter,
            yyyymmdd=day.strftime("%Y%m%d"),
        )

    def _discovery_dates(self, since: datetime, today: Optional[date] = None) -> list[date]:
        end = today or datetime.now().date()
        overlap_start = end - timedelta(days=SEC_DISCOVERY_DAYS - 1)
        start = max(since.date(), overlap_start)
        if start > end:
            return []
        return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]

    def _discover_candidates(
        self,
        since: datetime,
        today: Optional[date] = None,
    ) -> list[dict]:
        """Discover recent 8-K filings from daily EDGAR master indexes."""
        try:
            ticker_map = self._load_company_tickers()
        except Exception:
            # Submissions JSON also includes tickers, so mapping failure is non-fatal.
            ticker_map = {}

        # Large-cap filter: drop non-universe companies here, before any
        # per-CIK submissions fetch, so detail requests are never spent on
        # filings that would be discarded anyway.
        large_cap_ciks = self._large_cap_ciks(ticker_map)

        candidates: list[dict] = []
        seen_accessions: set[str] = set()

        for day in self._discovery_dates(since, today=today):
            try:
                response = self._get(self._daily_index_url(day))
            except Exception:
                continue

            if response.status_code != 200:
                # Weekends, holidays, and not-yet-published current-day indexes commonly 404.
                continue

            for row in self._parse_master_index(response.text):
                if large_cap_ciks is not None and row["cik"] not in large_cap_ciks:
                    continue
                accession = row["accession"]
                if accession in seen_accessions:
                    continue
                seen_accessions.add(accession)

                ticker, mapped_company = ticker_map.get(row["cik"], ("", ""))
                candidate = dict(row)
                candidate["ticker"] = ticker
                if mapped_company:
                    candidate["company"] = mapped_company
                candidates.append(candidate)

        return candidates

    def _events_from_payload(
        self,
        data: dict,
        since: datetime,
        allowed_accessions: Optional[set[str]] = None,
        ticker_override: str = "",
        company_override: str = "",
    ) -> list[RawEvent]:
        """Convert a SEC submissions payload into supported Event Radar events."""
        events: list[RawEvent] = []
        cik = str(data.get("cik", "")).zfill(10)
        company_name = company_override or data.get("name", "Unknown Corp")
        tickers = data.get("tickers", [])
        primary_ticker = ticker_override or (tickers[0] if tickers else "")
        if not primary_ticker:
            return events

        recent = data.get("filings", {}).get("recent", {})
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        acceptance_datetimes = recent.get("acceptanceDateTime", [])
        forms = recent.get("form", [])
        items_list = recent.get("items", [])
        descriptions = recent.get("primaryDocDescription", [])
        event_dates = recent.get("event_date", [])
        primary_docs = recent.get("primaryDocument", [])

        for i, acc_num in enumerate(accession_numbers):
            if allowed_accessions is not None and acc_num not in allowed_accessions:
                continue

            form = forms[i] if i < len(forms) else ""
            items_str = items_list[i] if i < len(items_list) else ""
            desc = descriptions[i] if i < len(descriptions) else ""

            ev_type = self._determine_event_type(form, items_str, desc)
            if not ev_type:
                continue

            f_date_str = filing_dates[i] if i < len(filing_dates) else ""
            try:
                ann_date = datetime.fromisoformat(f_date_str) if f_date_str else since
            except ValueError:
                ann_date = since
            if ann_date < since:
                continue

            accept_str = acceptance_datetimes[i] if i < len(acceptance_datetimes) else ""
            time_ctx = self._determine_time_context(accept_str)

            if i < len(event_dates) and event_dates[i]:
                ev_date = date.fromisoformat(str(event_dates[i])[:10])
            else:
                ev_date = self._extract_date(desc, default_date=ann_date.date())

            clean_acc = acc_num.replace("-", "")
            doc_name = primary_docs[i] if i < len(primary_docs) else ""
            doc_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{clean_acc}/{doc_name}"
                if cik and doc_name
                else ""
            )

            events.append(
                RawEvent(
                    source_name="SEC",
                    source_kind="REGULATOR",
                    source_event_uid=acc_num,
                    source_url=doc_url,
                    country="US",
                    primary_ticker=primary_ticker,
                    primary_company=company_name,
                    event_type=ev_type,
                    event_name=f"{company_name} {desc or form}".strip(),
                    announced_at=ann_date,
                    event_date=ev_date,
                    event_time_context=time_ctx,  # type: ignore
                    status="CONFIRMED",
                    evidence_text=f"{form} {items_str}: {desc}".strip(),
                    ingest_mode="AUTO",
                )
            )

        return events

    def _events_for_cik(
        self,
        cik: str,
        cik_candidates: list[dict],
        since: datetime,
    ) -> list[RawEvent]:
        """Fetch one company's submissions and convert its discovered filings."""
        try:
            response = self._get(SEC_SUBMISSIONS_URL.format(cik=cik))
            if response.status_code != 200:
                return []
            data = response.json()
        except Exception:
            return []

        allowed_accessions = {candidate["accession"] for candidate in cik_candidates}
        ticker_override = next(
            (candidate.get("ticker", "") for candidate in cik_candidates if candidate.get("ticker")),
            "",
        )
        company_override = next(
            (candidate.get("company", "") for candidate in cik_candidates if candidate.get("company")),
            "",
        )
        return self._events_from_payload(
            data,
            since=since,
            allowed_accessions=allowed_accessions,
            ticker_override=ticker_override,
            company_override=company_override,
        )

    def collect(self, since: datetime) -> list[RawEvent]:
        """Collect recent SEC corporate events without a manually maintained watchlist."""
        start_time = time.time()
        events: list[RawEvent] = []

        try:
            if self.fixture_path and self.fixture_path.exists():
                with open(self.fixture_path, mode="r", encoding="utf-8") as file_obj:
                    data = json.load(file_obj)
                events = self._events_from_payload(data, since=since)
            else:
                candidates = self._discover_candidates(since=since)
                by_cik: dict[str, list[dict]] = {}
                for candidate in candidates:
                    by_cik.setdefault(candidate["cik"], []).append(candidate)

                # A single earnings-season day can carry 700+ filing CIKs;
                # fetching submissions serially took tens of minutes and
                # timed out mid-run. Fetch per-CIK in parallel (the shared
                # rate limiter still caps request starts at SEC's limit).
                with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                    futures = [
                        pool.submit(self._events_for_cik, cik, cik_candidates, since)
                        for cik, cik_candidates in by_cik.items()
                    ]
                    for future in as_completed(futures):
                        events.extend(future.result())

            duration = time.time() - start_time
            log_collector_run(
                CollectorRunLog(
                    source_name=self.source_name,
                    status="SUCCESS",
                    items_count=len(events),
                    duration_sec=duration,
                )
            )
            return events

        except Exception as exc:
            duration = time.time() - start_time
            log_collector_run(
                CollectorRunLog(
                    source_name=self.source_name,
                    status="FAILED",
                    items_count=0,
                    duration_sec=duration,
                    error_message=str(exc),
                )
            )
            return []
