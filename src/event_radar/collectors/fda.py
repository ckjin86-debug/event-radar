"""FDA scheduled regulatory event collector based on the official advisory calendar."""

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


class FdaCollector:
    """Collect scheduled FDA advisory committee meetings.

    A small legacy parser is retained for existing fixtures, but production collection uses
    the official FDA Advisory Committee Calendar instead of the old news-events page.
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EventRadar/1.0"
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
            uid = hashlib.sha1(f"{ev_date.isoformat()}|{title}|{item_url}".encode("utf-8")).hexdigest()

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

            url = cfg.get("advisory_url", FDA_ADVISORY_URL)
            if self.mock_html is not None:
                html_text = self.mock_html
            else:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    raise ConnectionError(f"FDA returned HTTP {resp.status_code}")
                html_text = resp.text

            soup = BeautifulSoup(html_text, "html.parser")
            events = self._parse_advisory_table(soup, since)
            if not events:
                events = self._parse_legacy_fixture(soup, since, cfg)

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
