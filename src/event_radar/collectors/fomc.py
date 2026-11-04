"""Federal Reserve FOMC scheduled decision collector."""

from __future__ import annotations

import calendar
import hashlib
import re
import time
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup, Tag
import requests

from event_radar.collectors.base import CollectorRunLog, log_collector_run
from event_radar.models import RawEvent


FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): number for number, name in enumerate(calendar.month_abbr) if name})
_MONTH_PATTERN = "|".join(calendar.month_name[1:])
_DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})(?:\s*[-–—]\s*(\d{1,2}))?\s*\*?(?!\d)")


def _decision_date(year: int, month_name: str, date_text: str) -> Optional[date]:
    if "notation" in date_text.lower():
        return None
    month = MONTHS.get(month_name.strip().split("/")[-1].strip().lower())
    if month is None:
        return None
    match = _DATE_PATTERN.search(date_text)
    if not match:
        return None
    day = int(match.group(2) or match.group(1))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _find_year_for_node(node: Tag) -> Optional[int]:
    heading = node.find_previous(["h2", "h3", "h4", "h5"])
    while heading is not None:
        text = heading.get_text(" ", strip=True)
        match = re.search(r"(20\d{2})\s+FOMC\s+Meetings", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        heading = heading.find_previous(["h2", "h3", "h4", "h5"])
    return None


class FomcCollector:
    source_name = "FED_FOMC"

    def __init__(self, mock_html: Optional[str] = None, timeout: int = 10, history_start: date | None = None) -> None:
        self.mock_html = mock_html
        self.timeout = timeout
        self.history_start = history_start
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EventRadar/1.0"
        })

    @staticmethod
    def _make_event(ev_date: date, evidence: str) -> RawEvent:
        uid = hashlib.sha1(f"FOMC|{ev_date.isoformat()}".encode("utf-8")).hexdigest()
        return RawEvent(
            source_name="FED_FOMC",
            source_kind="REGULATOR",
            source_event_uid=uid,
            source_url=FOMC_CALENDAR_URL,
            country="US",
            primary_ticker="^GSPC",
            primary_company="Federal Reserve",
            event_type="FOMC_DECISION",
            event_name=f"FOMC policy decision {ev_date.isoformat()}",
            announced_at=datetime.combine(ev_date, datetime.min.time()),
            event_date=ev_date,
            date_precision="EXACT_DATE",
            window_start=ev_date,
            window_end=ev_date,
            event_time_context="INTRADAY",
            status="CONFIRMED",
            evidence_text=evidence,
            ingest_mode="AUTO",
        )

    def _parse_structured(self, soup: BeautifulSoup, since: datetime) -> list[RawEvent]:
        events: list[RawEvent] = []
        seen: set[date] = set()
        for node in soup.select(".fomc-meeting"):
            # Avoid matching nested month/date elements that may themselves carry a shared class.
            month_node = node.select_one(".fomc-meeting__month")
            date_node = node.select_one(".fomc-meeting__date")
            if month_node is None or date_node is None:
                continue
            year = _find_year_for_node(node)
            if year is None:
                continue
            month_text = month_node.get_text(" ", strip=True)
            date_text = date_node.get_text(" ", strip=True)
            ev_date = _decision_date(year, month_text, date_text)
            if ev_date is None or ev_date < since.date() or ev_date in seen:
                continue
            seen.add(ev_date)
            events.append(self._make_event(ev_date, f"{year} {month_text} {date_text}"))
        return events

    def _parse_text_fallback(self, soup: BeautifulSoup, since: datetime) -> list[RawEvent]:
        """Fallback for minor Fed markup changes, constrained to FOMC meeting sections."""
        events: list[RawEvent] = []
        seen: set[date] = set()
        strings = [s.strip() for s in soup.stripped_strings if s.strip()]
        current_year: Optional[int] = None

        for idx, text in enumerate(strings):
            year_match = re.search(r"(20\d{2})\s+FOMC\s+Meetings", text, re.IGNORECASE)
            if year_match:
                current_year = int(year_match.group(1))
                continue
            if current_year is None or text.lower() not in MONTHS:
                continue

            # The official page places the meeting date immediately after the month label.
            date_text = ""
            for candidate in strings[idx + 1: idx + 5]:
                if _DATE_PATTERN.fullmatch(candidate.strip()):
                    date_text = candidate
                    break
                # Stop before wandering into the next meeting/month or unrelated release metadata.
                if candidate.lower() in MONTHS or re.search(r"20\d{2}\s+FOMC\s+Meetings", candidate, re.IGNORECASE):
                    break
            if not date_text:
                continue
            ev_date = _decision_date(current_year, text, date_text)
            if ev_date is None or ev_date < since.date() or ev_date in seen:
                continue
            seen.add(ev_date)
            events.append(self._make_event(ev_date, f"{current_year} {text} {date_text}"))

        return events

    def collect(self, since: datetime) -> list[RawEvent]:
        started = time.time()
        try:
            if self.mock_html is not None:
                html_text = self.mock_html
            else:
                response = self.session.get(FOMC_CALENDAR_URL, timeout=self.timeout)
                if response.status_code != 200:
                    raise ConnectionError(f"Federal Reserve returned HTTP {response.status_code}")
                html_text = response.text

            soup = BeautifulSoup(html_text, "html.parser")
            if self.history_start:
                since = min(since, datetime.combine(self.history_start, datetime.min.time()))
            events = self._parse_structured(soup, since)
            if not events:
                events = self._parse_text_fallback(soup, since)
            events.sort(key=lambda event: event.event_date)

            log_collector_run(
                CollectorRunLog(
                    source_name=self.source_name,
                    status="SUCCESS",
                    items_count=len(events),
                    duration_sec=time.time() - started,
                )
            )
            return events
        except Exception as exc:
            log_collector_run(
                CollectorRunLog(
                    source_name=self.source_name,
                    status="FAILED",
                    items_count=0,
                    duration_sec=time.time() - started,
                    error_message=str(exc),
                )
            )
            return []
