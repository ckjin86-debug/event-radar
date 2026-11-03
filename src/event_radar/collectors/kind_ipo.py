"""KRX KIND IPO schedule collector."""

from __future__ import annotations

import hashlib
import re
import time
from collections import defaultdict
from datetime import date, datetime
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests

from event_radar.collectors.base import CollectorRunLog, log_collector_run
from event_radar.models import RawEvent


KIND_IPO_URL = "https://kind.krx.co.kr/listinvstg/pubofrschdl.do?method=searchPubofrScholMain"
KIND_CALENDAR_POST_URL = "https://kind.krx.co.kr/listinvstg/pubofrschdl.do"
KIND_BASE_URL = "https://kind.krx.co.kr"


_DATE_RE = re.compile(r"(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})")
_CALENDAR_MONTH_RE = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월")
_ALLOWED_CALENDAR_LABELS = {"수요예측", "청약", "납입", "상장"}


def _parse_dates(text: str) -> list[date]:
    dates: list[date] = []
    for year, month, day in _DATE_RE.findall(text or ""):
        try:
            parsed = date(int(year), int(month), int(day))
        except ValueError:
            continue
        if parsed not in dates:
            dates.append(parsed)
    return dates


def _norm_header(text: str) -> str:
    return re.sub(r"\s+", "", text or "").replace("(예정)", "")


def _find_index(headers: list[str], *needles: str) -> Optional[int]:
    for idx, header in enumerate(headers):
        normalized = _norm_header(header)
        if any(needle in normalized for needle in needles):
            return idx
    return None


def _add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    zero_based = (year * 12 + (month - 1)) + offset
    return zero_based // 12, zero_based % 12 + 1


class KindIpoCollector:
    source_name = "KIND_IPO"

    def __init__(self, mock_html: Optional[str] = None, timeout: int = 10, months_ahead: int = 2) -> None:
        self.mock_html = mock_html
        self.timeout = timeout
        self.months_ahead = max(0, months_ahead)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EventRadar/1.0",
            "Referer": KIND_IPO_URL,
        })

    @staticmethod
    def _market_proxy(market_text: str) -> str:
        upper = (market_text or "").upper()
        if "코스닥" in market_text or "KOSDAQ" in upper or "코넥스" in market_text or "KONEX" in upper:
            return "^KQ11"
        if "유가증권" in market_text or "코스피" in market_text or "KOSPI" in upper:
            return "^KS11"
        return "^KS11"

    @staticmethod
    def _make_event(
        company: str,
        ticker: str,
        event_type: str,
        label: str,
        event_date: date,
        source_url: str,
        evidence: str,
        announced_at: datetime,
    ) -> RawEvent:
        # Keep the source UID independent of the scheduled date so corrections become revisions.
        uid = hashlib.sha1(f"{company}|{event_type}|{source_url}".encode("utf-8")).hexdigest()
        return RawEvent(
            source_name="KIND_IPO",
            source_kind="EXCHANGE",
            source_event_uid=uid,
            source_url=source_url,
            country="KR",
            primary_ticker=ticker,
            primary_company=company,
            event_type=event_type,
            event_name=f"{company} {label}",
            announced_at=announced_at,
            event_date=event_date,
            date_precision="EXACT_DATE",
            window_start=event_date,
            window_end=event_date,
            event_time_context="DATE_ONLY",
            status="CONFIRMED",
            evidence_text=evidence,
            ingest_mode="AUTO",
        )

    def _parse_table(self, html_text: str, since: datetime) -> list[RawEvent]:
        """Legacy table parser retained for old fixtures and possible KIND layout fallbacks."""
        soup = BeautifulSoup(html_text, "html.parser")
        events: list[RawEvent] = []

        for table in soup.find_all("table"):
            header_cells = table.find_all("th")
            headers = [cell.get_text(" ", strip=True) for cell in header_cells]
            if not headers:
                continue

            company_idx = _find_index(headers, "회사명", "종목명", "기업명")
            market_idx = _find_index(headers, "시장구분", "시장")
            book_idx = _find_index(headers, "수요예측")
            subscription_idx = _find_index(headers, "청약")
            payment_idx = _find_index(headers, "납입")
            listing_idx = _find_index(headers, "상장예정", "상장일", "상장")
            if company_idx is None or not any(
                idx is not None for idx in (book_idx, subscription_idx, payment_idx, listing_idx)
            ):
                continue

            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if not cells or company_idx >= len(cells):
                    continue

                company_cell = cells[company_idx]
                company = company_cell.get_text(" ", strip=True)
                if not company:
                    continue
                link = company_cell.find("a", href=True)
                source_url = urljoin(KIND_BASE_URL, link.get("href", "")) if link else KIND_IPO_URL
                market_text = cells[market_idx].get_text(" ", strip=True) if market_idx is not None and market_idx < len(cells) else ""
                ticker = self._market_proxy(market_text)
                evidence = " | ".join(cell.get_text(" ", strip=True) for cell in cells)

                def add_range(idx: Optional[int], start_type: str, start_label: str, end_type: str, end_label: str) -> None:
                    if idx is None or idx >= len(cells):
                        return
                    parsed_dates = _parse_dates(cells[idx].get_text(" ", strip=True))
                    if not parsed_dates:
                        return
                    first = parsed_dates[0]
                    last = parsed_dates[-1]
                    if first >= since.date():
                        events.append(self._make_event(company, ticker, start_type, start_label, first, source_url, evidence, since))
                    if last >= since.date():
                        events.append(self._make_event(company, ticker, end_type, end_label, last, source_url, evidence, since))

                def add_single(idx: Optional[int], event_type: str, label: str) -> None:
                    if idx is None or idx >= len(cells):
                        return
                    parsed_dates = _parse_dates(cells[idx].get_text(" ", strip=True))
                    if not parsed_dates:
                        return
                    ev_date = parsed_dates[-1]
                    if ev_date >= since.date():
                        events.append(self._make_event(company, ticker, event_type, label, ev_date, source_url, evidence, since))

                add_range(book_idx, "IPO_BOOKBUILDING_START", "수요예측 시작", "IPO_BOOKBUILDING_END", "수요예측 종료")
                add_range(subscription_idx, "IPO_SUBSCRIPTION_START", "공모청약 시작", "IPO_SUBSCRIPTION_END", "공모청약 종료")
                add_single(payment_idx, "IPO_PAYMENT", "납입일")
                add_single(listing_idx, "IPO_LISTING", "상장예정일")

        events.sort(key=lambda e: (e.event_date, e.primary_company, e.event_type))
        return events

    def _parse_calendar_entries(self, html_text: str) -> list[dict]:
        """Parse the official KIND monthly calendar into date/category/company entries."""
        soup = BeautifulSoup(html_text, "html.parser")
        calendar = soup.select_one("#calBig2") or soup
        month_match = _CALENDAR_MONTH_RE.search(calendar.get_text(" ", strip=True))
        if not month_match:
            return []
        year, month = int(month_match.group(1)), int(month_match.group(2))
        entries: list[dict] = []

        for cell in calendar.find_all("td"):
            cell_text = cell.get_text(" ", strip=True)
            day_match = re.match(r"^(3[01]|[12]\d|0?[1-9])(?:\s|$)", cell_text)
            if not day_match:
                continue
            try:
                ev_date = date(year, month, int(day_match.group(1)))
            except ValueError:
                continue

            current_label: Optional[str] = None
            for item in cell.find_all("li"):
                strong = item.find("strong")
                if strong:
                    label = strong.get_text(" ", strip=True)
                    current_label = label if label in _ALLOWED_CALENDAR_LABELS else None
                    continue
                if current_label is None:
                    continue
                company = item.get_text(" ", strip=True)
                if not company:
                    continue
                market_img = item.find("img")
                market = market_img.get("alt", "") if market_img else ""
                link = item.find("a", href=True)
                source_url = urljoin(KIND_BASE_URL, link.get("href", "")) if link else KIND_IPO_URL
                entries.append({
                    "date": ev_date,
                    "category": current_label,
                    "company": company,
                    "market": market,
                    "source_url": source_url,
                })
        return entries

    def _events_from_calendar_entries(self, entries: list[dict], since: datetime) -> list[RawEvent]:
        grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for entry in entries:
            if entry["date"] < since.date():
                continue
            grouped[(entry["company"], entry["category"], entry["market"])].append(entry)

        events: list[RawEvent] = []
        for (company, category, market), rows in grouped.items():
            rows.sort(key=lambda row: row["date"])
            ticker = self._market_proxy(market)
            source_url = rows[0]["source_url"] or KIND_IPO_URL
            dates = sorted({row["date"] for row in rows})
            evidence = f"KIND 공모일정: {category} {dates[0].isoformat()}" + (f"~{dates[-1].isoformat()}" if dates[-1] != dates[0] else "")

            if category == "수요예측":
                events.append(self._make_event(company, ticker, "IPO_BOOKBUILDING_START", "수요예측 시작", dates[0], source_url, evidence, since))
                events.append(self._make_event(company, ticker, "IPO_BOOKBUILDING_END", "수요예측 종료", dates[-1], source_url, evidence, since))
            elif category == "청약":
                events.append(self._make_event(company, ticker, "IPO_SUBSCRIPTION_START", "공모청약 시작", dates[0], source_url, evidence, since))
                events.append(self._make_event(company, ticker, "IPO_SUBSCRIPTION_END", "공모청약 종료", dates[-1], source_url, evidence, since))
            elif category == "납입":
                events.append(self._make_event(company, ticker, "IPO_PAYMENT", "납입일", dates[-1], source_url, evidence, since))
            elif category == "상장":
                events.append(self._make_event(company, ticker, "IPO_LISTING", "상장예정일", dates[-1], source_url, evidence, since))

        # Remove exact duplicates that can occur when adjacent monthly pages overlap.
        deduped: dict[tuple[str, str, date], RawEvent] = {}
        for event in events:
            deduped[(event.primary_company, event.event_type, event.event_date)] = event
        return sorted(deduped.values(), key=lambda e: (e.event_date, e.primary_company, e.event_type))

    def _fetch_calendar_month(self, year: int, month: int) -> str:
        response = self.session.post(
            KIND_CALENDAR_POST_URL,
            data={
                "method": "searchPubofrScholCalnd",
                "forward": "pubofrSchol_sub",
                "marketType": "",
                "scholType": "",
                "selYear": str(year),
                "selMonth": f"{month:02d}",
            },
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise ConnectionError(f"KIND returned HTTP {response.status_code}")
        response.encoding = response.apparent_encoding or response.encoding
        return response.text

    def collect(self, since: datetime) -> list[RawEvent]:
        started = time.time()
        try:
            if self.mock_html is not None:
                calendar_entries = self._parse_calendar_entries(self.mock_html)
                events = self._events_from_calendar_entries(calendar_entries, since) if calendar_entries else self._parse_table(self.mock_html, since)
            else:
                # Use current month plus the next months so future IPO milestones are visible before they become near-term.
                today = datetime.now().date()
                all_entries: list[dict] = []
                for offset in range(self.months_ahead + 1):
                    year, month = _add_months(today.year, today.month, offset)
                    html_text = self._fetch_calendar_month(year, month)
                    all_entries.extend(self._parse_calendar_entries(html_text))
                events = self._events_from_calendar_entries(all_entries, since)

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
