"""KRX KIND IPO schedule collector."""

from __future__ import annotations

import hashlib
import re
import time
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

    def __init__(self, mock_html: Optional[str] = None, timeout: int = 10) -> None:
        self.mock_html = mock_html
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EventRadar/1.0"
        })

    @staticmethod
    def _market_proxy(market_text: str) -> str:
        upper = (market_text or "").upper()
        if "코스닥" in market_text or "KOSDAQ" in upper:
            return "^KQ11"
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
        uid = hashlib.sha1(
            f"{company}|{event_type}|{event_date.isoformat()}|{source_url}".encode("utf-8")
        ).hexdigest()
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

                add_range(
                    book_idx,
                    "IPO_BOOKBUILDING_START",
                    "수요예측 시작",
                    "IPO_BOOKBUILDING_END",
                    "수요예측 종료",
                )
                add_range(
                    subscription_idx,
                    "IPO_SUBSCRIPTION_START",
                    "공모청약 시작",
                    "IPO_SUBSCRIPTION_END",
                    "공모청약 종료",
                )
                add_single(payment_idx, "IPO_PAYMENT", "납입일")
                add_single(listing_idx, "IPO_LISTING", "상장예정일")

        events.sort(key=lambda e: (e.event_date, e.primary_company, e.event_type))
        return events

    def collect(self, since: datetime) -> list[RawEvent]:
        started = time.time()
        try:
            if self.mock_html is not None:
                html_text = self.mock_html
            else:
                response = self.session.get(KIND_IPO_URL, timeout=self.timeout)
                if response.status_code != 200:
                    raise ConnectionError(f"KIND returned HTTP {response.status_code}")
                response.encoding = response.apparent_encoding or response.encoding
                html_text = response.text

            events = self._parse_table(html_text, since)
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
