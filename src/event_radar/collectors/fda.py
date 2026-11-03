"""FDA scheduled regulatory event collector based on official government sources."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests
import yaml

from event_radar.models import RawEvent
from event_radar.collectors.base import CollectorRunLog, log_collector_run


FDA_ADVISORY_URL = "https://www.fda.gov/advisory-committees/advisory-committee-calendar"
FEDERAL_REGISTER_API_URL = "https://www.federalregister.gov/api/v1/documents.json"

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


class FdaCollector:
    """Collect scheduled FDA advisory committee meetings.

    Production first tries the FDA advisory calendar. Some cloud runners receive a 404
    from that page, so the collector falls back to the Federal Register public API,
    where FDA advisory committee meeting notices are officially published.
    """

    source_name: str = "FDA_ADVISORY"

    def __init__(
        self,
        config_path: Path | str = "config/site_registry.yaml",
        mock_html: Optional[str] = None,
        timeout: int = 10,
    ):
        self.config_path = Path(config_path)
        self.mock_html = mock_html
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EventRadar/1.0",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    @staticmethod
    def _parse_us_date(text: str) -> Optional[date]:
        match = re.search(r"(?<!\d)(1[0-2]|0?[1-9])/(3[01]|[12]\d|0?[1-9])/(20\d{2})(?!\d)", text)
        if not match:
            return None
        try:
            return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None

    @staticmethod
    def _parse_written_date(text: str) -> Optional[date]:
        pattern = r"\b(" + "|".join(_MONTHS.keys()) + r")\s+(3[01]|[12]\d|0?[1-9]),\s*(20\d{2})\b"
        match = re.search(pattern, text or "", re.IGNORECASE)
        if not match:
            return None
        try:
            return date(int(match.group(3)), _MONTHS[match.group(1).lower()], int(match.group(2)))
        except ValueError:
            return None

    @staticmethod
    def _ticker_and_company(title: str) -> tuple[str, str]:
        match = re.search(r"\((?:NASDAQ|NYSE|AMEX|Ticker)\s*:\s*([A-Z0-9.\-]{1,10})\)", title, re.IGNORECASE)
        if match:
            ticker = match.group(1).upper()
            company_match = re.search(r"\bfor\s+(.+?)\s*\((?:NASDAQ|NYSE|AMEX|Ticker)\s*:", title, re.IGNORECASE)
            company = company_match.group(1).strip(" ,:-") if company_match else "FDA Applicant"
            return ticker, company
        return "XBI", "FDA Advisory Committee"

    def _parse_advisory_table(self, soup: BeautifulSoup, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []
        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            row_text = " ".join(cell.get_text(" ", strip=True) for cell in cells)
            ev_date = self._parse_us_date(row_text)
            if ev_date is None or ev_date < since.date():
                continue

            meeting_cell = next((cell for cell in cells[1:] if cell.get_text(" ", strip=True)), cells[-1])
            link = meeting_cell.find("a", href=True)
            title = meeting_cell.get_text(" ", strip=True)
            if not title:
                continue
            item_url = urljoin("https://www.fda.gov", link.get("href", "")) if link else FDA_ADVISORY_URL
            ticker, company = self._ticker_and_company(title)
            uid = hashlib.sha1(f"{title}|{item_url}".encode("utf-8")).hexdigest()

            events.append(
                RawEvent(
                    source_name=self.source_name,
                    source_kind="REGULATOR",
                    source_event_uid=uid,
                    source_url=item_url,
                    country="US",
                    primary_ticker=ticker,
                    primary_company=company,
                    event_type="FDA_ADVISORY_COMMITTEE",
                    event_name=title,
                    announced_at=since,
                    event_date=ev_date,
                    date_precision="EXACT_DATE",
                    window_start=ev_date,
                    window_end=ev_date,
                    event_time_context="DATE_ONLY",
                    status="CONFIRMED",
                    evidence_text=title,
                    ingest_mode="AUTO",
                )
            )
        return events

    def _parse_federal_register_payload(self, payload: dict, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []
        for item in payload.get("results", []) or []:
            title = str(item.get("title") or "").strip()
            abstract = str(item.get("abstract") or "").strip()
            excerpts = str(item.get("excerpts") or "").strip()
            combined = " ".join(part for part in (title, abstract, excerpts) if part)

            # Avoid nominations/administrative notices that merely mention committees.
            title_lower = title.lower()
            if "meeting" not in title_lower or "advisory" not in title_lower:
                continue
            ev_date = self._parse_written_date(excerpts) or self._parse_written_date(combined)
            if ev_date is None or ev_date < since.date():
                continue

            publication_raw = str(item.get("publication_date") or "")
            try:
                announced_at = datetime.combine(date.fromisoformat(publication_raw), datetime.min.time())
            except ValueError:
                announced_at = since
            source_url = str(item.get("html_url") or "https://www.federalregister.gov/")
            doc_no = str(item.get("document_number") or "").strip()
            ticker, company = self._ticker_and_company(title)
            source_uid = f"federal-register:{doc_no}" if doc_no else hashlib.sha1(source_url.encode("utf-8")).hexdigest()

            events.append(
                RawEvent(
                    source_name=self.source_name,
                    source_kind="REGULATOR",
                    source_event_uid=source_uid,
                    source_url=source_url,
                    country="US",
                    primary_ticker=ticker,
                    primary_company=company,
                    event_type="FDA_ADVISORY_COMMITTEE",
                    event_name=title,
                    announced_at=announced_at,
                    event_date=ev_date,
                    date_precision="EXACT_DATE",
                    window_start=ev_date,
                    window_end=ev_date,
                    event_time_context="DATE_ONLY",
                    status="CONFIRMED",
                    evidence_text=excerpts or abstract or title,
                    ingest_mode="AUTO",
                )
            )

        deduped: dict[str, RawEvent] = {}
        for event in events:
            deduped[event.source_event_uid or event.source_url] = event
        return sorted(deduped.values(), key=lambda e: (e.event_date, e.event_name))

    def _fetch_federal_register_events(self, since: datetime) -> list[RawEvent]:
        response = self.session.get(
            FEDERAL_REGISTER_API_URL,
            params={
                "per_page": 100,
                "order": "newest",
                "conditions[agencies][]": "food-and-drug-administration",
                "conditions[term]": "advisory committee meeting",
            },
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise ConnectionError(f"Federal Register returned HTTP {response.status_code}")
        return self._parse_federal_register_payload(response.json(), since)

    def _parse_legacy_fixture(self, soup: BeautifulSoup, since: datetime, cfg: dict) -> list[RawEvent]:
        """Keep the old test/fixture contract without using it for production discovery."""
        events: list[RawEvent] = []
        container_sel = cfg.get("container_selector", ".view-content .views-row")
        title_sel = cfg.get("title_selector", ".views-field-title a")
        for item in soup.select(container_sel):
            title_elem = item.select_one(title_sel)
            if not title_elem:
                continue
            title_text = title_elem.get_text(strip=True)
            item_url = urljoin("https://www.fda.gov", title_elem.get("href", ""))
            ticker_match = re.search(r"Ticker:\s*([A-Z0-9.\-]+)", title_text, re.IGNORECASE)
            if not ticker_match:
                ticker_match = re.search(r"\(([A-Z]{1,5})\)", title_text)
            date_match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", title_text)
            if not ticker_match or not date_match:
                continue
            ev_date = date(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
            events.append(
                RawEvent(
                    source_name=self.source_name,
                    source_kind="REGULATOR",
                    source_url=item_url,
                    country="US",
                    primary_ticker=ticker_match.group(1).upper(),
                    primary_company="FDA Applicant",
                    event_type="FDA_APPROVAL",
                    event_name=title_text,
                    announced_at=since,
                    event_date=ev_date,
                    event_time_context="DATE_ONLY",
                    status="CONFIRMED",
                    evidence_text=title_text,
                    ingest_mode="AUTO",
                )
            )
        return events

    def collect(self, since: datetime) -> list[RawEvent]:
        start_time = time.time()
        try:
            cfg: dict = {}
            if self.config_path.exists():
                with open(self.config_path, mode="r", encoding="utf-8") as f:
                    all_cfg = yaml.safe_load(f) or {}
                    cfg = all_cfg.get("sources", {}).get("fda_pdufa", {})

            if self.mock_html is not None:
                soup = BeautifulSoup(self.mock_html, "html.parser")
                events = self._parse_advisory_table(soup, since)
                if not events:
                    events = self._parse_legacy_fixture(soup, since, cfg)
            else:
                url = cfg.get("advisory_url", FDA_ADVISORY_URL)
                events: list[RawEvent] = []
                primary_error: Optional[Exception] = None
                try:
                    resp = self.session.get(url, timeout=self.timeout)
                    if resp.status_code != 200:
                        raise ConnectionError(f"FDA returned HTTP {resp.status_code}")
                    soup = BeautifulSoup(resp.text, "html.parser")
                    events = self._parse_advisory_table(soup, since)
                except Exception as exc:
                    primary_error = exc

                # Federal Register is an official public source and requires no API key.
                if not events:
                    try:
                        events = self._fetch_federal_register_events(since)
                    except Exception as fallback_exc:
                        if primary_error is not None:
                            raise ConnectionError(f"FDA primary failed ({primary_error}); Federal Register fallback failed ({fallback_exc})") from fallback_exc
                        raise

            log_collector_run(
                CollectorRunLog(
                    source_name=self.source_name,
                    status="SUCCESS",
                    items_count=len(events),
                    duration_sec=time.time() - start_time,
                )
            )
            return events
        except Exception as exc:
            log_collector_run(
                CollectorRunLog(
                    source_name=self.source_name,
                    status="FAILED",
                    items_count=0,
                    duration_sec=time.time() - start_time,
                    error_message=str(exc),
                )
            )
            return []
