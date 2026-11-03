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


KIND_IPO_URL = "https://kind.krx.co.kr/listinvstg/pubofrprogcom.do?method=searchPubofrProgComMain"
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


class KindIpoCollector:
    source_name = "KIND_IPO"

    def __init__(self, mock_html: Optional[str] = None, timeout: int = 10, months_ahead: int = 2) -> None:
        self.mock_html = mock_html
        self.timeout = timeout
        # Retained for constructor compatibility. The server-rendered public-offering
        # company page already includes upcoming bookbuilding/subscription/listing dates.
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
        """Parse KIND's server-rendered public-offering company table."""
        soup = BeautifulSoup(html_text, "html.parser")
        events: list[RawEvent] = []
        for table in soup.find_all("table"):
            headers = [cell.get_text(" ", strip=True) for cell in table.find_all("th")]
            if not headers:
                continue
            company_idx = _find_index(headers, "회사명", "종목명", "기업명")
            market_idx = _find_index(headers, "시장구분", "시장")
            book_idx = _find_index(headers, "수요예측")
            subscription_idx = _find_index(headers, "청약")
            payment_idx = _find_index(headers, "납입")
            listing_idx = _find_index(headers, "상장예정", "상장일", "상장")
            if company_idx is None or not any(idx is not None for idx in (book_idx, subscription_idx, payment_idx, listing_idx)):
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

                if market_idx is not None and market_idx < len(cells):
                    market_text = cells[market_idx].get_text(" ", strip=True)
                else:
                    # Current KIND markup puts the market badge inside the company cell,
                    # e.g. <img alt="코스닥"> rather than exposing a market column.
                    market_img = company_cell.find("img")
                    market_text = market_img.get("alt", "") if market_img else ""
                ticker = self._market_proxy(market_text)
                evidence = " | ".join(cell.get_text(" ", strip=True) for cell in cells)

                def add_range(idx: Optional[int], start_type: str, start_label: str, end_type: str, end_label: str) -> None:
                    if idx is None or idx >= len(cells):
                        return
                    parsed = _parse_dates(cells[idx].get_text(" ", strip=True))
                    if not parsed:
                        return
                    if parsed[0] >= since.date():
                        events.append(self._make_event(company, ticker, start_type, start_label, parsed[0], source_url, evidence, since))
                    if parsed[-1] >= since.date():
                        events.append(self._make_event(company, ticker, end_type, end_label, parsed[-1], source_url, evidence, since))

                def add_single(idx: Optional[int], event_type: str, label: str) -> None:
                    if idx is None or idx >= len(cells):
                        return
                    parsed = _parse_dates(cells[idx].get_text(" ", strip=True))
                    if parsed and parsed[-1] >= since.date():
                        events.append(self._make_event(company, ticker, event_type, label, parsed[-1], source_url, evidence, since))

                add_range(book_idx, "IPO_BOOKBUILDING_START", "수요예측 시작", "IPO_BOOKBUILDING_END", "수요예측 종료")
                add_range(subscription_idx, "IPO_SUBSCRIPTION_START", "공모청약 시작", "IPO_SUBSCRIPTION_END", "공모청약 종료")
                add_single(payment_idx, "IPO_PAYMENT", "납입일")
                add_single(listing_idx, "IPO_LISTING", "상장예정일")

        return sorted(events, key=lambda e: (e.event_date, e.primary_company, e.event_type))

    def _parse_calendar_entries(self, html_text: str) -> list[dict]:
        """Retain calendar parsing for fixtures/backward compatibility."""
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
            if entry["date"] >= since.date():
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

        deduped = {(event.primary_company, event.event_type, event.event_date): event for event in events}
        return sorted(deduped.values(), key=lambda e: (e.event_date, e.primary_company, e.event_type))

    def _fetch_public_offering_table(self) -> str:
        response = self.session.get(KIND_IPO_URL, timeout=self.timeout)
        if response.status_code != 200:
            raise ConnectionError(f"KIND returned HTTP {response.status_code}")
        if hasattr(response, "apparent_encoding"):
            response.encoding = response.apparent_encoding or response.encoding
        return response.text

    def collect(self, since: datetime) -> list[RawEvent]:
        started = time.time()
        try:
            if self.mock_html is not None:
                html_text = self.mock_html
            else:
                html_text = self._fetch_public_offering_table()

            # Production uses the public-offering company table because it contains
            # bookbuilding, subscription, payment and listing dates in one stable page.
            events = self._parse_table(html_text, since)
            if not events:
                calendar_entries = self._parse_calendar_entries(html_text)
                events = self._events_from_calendar_entries(calendar_entries, since) if calendar_entries else []

            log_collector_run(CollectorRunLog(
                source_name=self.source_name,
                status="SUCCESS",
                items_count=len(events),
                duration_sec=time.time() - started,
            ))
            return events
        except Exception as exc:
            log_collector_run(CollectorRunLog(
                source_name=self.source_name,
                status="FAILED",
                items_count=0,
                duration_sec=time.time() - started,
                error_message=str(exc),
            ))
            return []
