"""Future-oriented Korean market event discovery from NAVER API HUB news search."""

from __future__ import annotations

import calendar
import hashlib
import html
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Iterable, Optional

import requests

from event_radar.collectors.base import CollectorRunLog, log_collector_run
from event_radar.models import RawEvent


NAVER_NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
DEFAULT_QUERIES = [
    "내달 가동",
    "다음달 출시",
    "연내 승인",
    "내년 1분기 가동",
    "상장 예정",
    "임상 결과 예정",
    "정책 시행 예정",
    "수주 발표 예정",
]


@dataclass(frozen=True)
class FutureWindow:
    precision: str
    start: date
    end: date
    matched_text: str = ""


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _next_month(ref: date) -> tuple[int, int]:
    if ref.month == 12:
        return ref.year + 1, 1
    return ref.year, ref.month + 1


def parse_future_window(text: str, reference_date: date) -> Optional[FutureWindow]:
    """Parse a Korean future-time expression into a bounded date window."""
    normalized = html.unescape(re.sub(r"<[^>]+>", " ", text))

    # 내년 N분기
    m = re.search(r"내년\s*([1-4])\s*분기", normalized)
    if m:
        quarter = int(m.group(1))
        year = reference_date.year + 1
        start_month = (quarter - 1) * 3 + 1
        start = date(year, start_month, 1)
        end_month = start_month + 2
        end = date(year, end_month, calendar.monthrange(year, end_month)[1])
        return FutureWindow("QUARTER", start, end, m.group(0))

    # N월 N일: infer next year if this year's date is already past.
    m = re.search(r"(?<!\d)(1[0-2]|0?[1-9])\s*월\s*(3[01]|[12]?\d)\s*일", normalized)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        try:
            candidate = date(reference_date.year, month, day)
        except ValueError:
            return None
        if candidate < reference_date:
            try:
                candidate = date(reference_date.year + 1, month, day)
            except ValueError:
                return None
        return FutureWindow("EXACT_DATE", candidate, candidate, m.group(0))

    # 오는 N일 means the next occurrence of that day number, normally this month.
    m = re.search(r"오는\s*(3[01]|[12]?\d)\s*일", normalized)
    if m:
        day = int(m.group(1))
        year, month = reference_date.year, reference_date.month
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = reference_date
        if candidate < reference_date:
            year, month = _next_month(reference_date)
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None
        return FutureWindow("EXACT_DATE", candidate, candidate, m.group(0))

    # 내달 / 다음달
    m = re.search(r"(?:내달|다음달)", normalized)
    if m:
        year, month = _next_month(reference_date)
        start, end = _month_bounds(year, month)
        return FutureWindow("MONTH", start, end, m.group(0))

    # explicit month only
    m = re.search(r"(?<!\d)(1[0-2]|0?[1-9])\s*월(?!\s*\d+\s*일)", normalized)
    if m:
        month = int(m.group(1))
        year = reference_date.year + (1 if month < reference_date.month else 0)
        start, end = _month_bounds(year, month)
        return FutureWindow("MONTH", start, end, m.group(0))

    # 내년 상/하반기
    m = re.search(r"내년\s*(상반기|하반기)", normalized)
    if m:
        year = reference_date.year + 1
        if m.group(1) == "상반기":
            return FutureWindow("HALF_YEAR", date(year, 1, 1), date(year, 6, 30), m.group(0))
        return FutureWindow("HALF_YEAR", date(year, 7, 1), date(year, 12, 31), m.group(0))

    # 연내
    m = re.search(r"연내", normalized)
    if m:
        return FutureWindow("YEAR", reference_date, date(reference_date.year, 12, 31), m.group(0))

    return None


def classify_catalyst(text: str) -> Optional[str]:
    """Return a market-relevant event type or None for low-signal text."""
    normalized = html.unescape(re.sub(r"<[^>]+>", " ", text))

    if "유상증자" in normalized:
        if re.search(r"시설투자|설비투자|시설자금|공장|증설|CAPEX", normalized, re.IGNORECASE):
            return "CAPEX_FINANCING"
        return None

    rules: list[tuple[str, str]] = [
        (r"상업\s*가동|공장.{0,12}가동|라인.{0,12}가동|생산.{0,8}가동", "PLANT_OPERATION"),
        (r"FDA.{0,12}(?:승인|허가)|승인\s*(?:예정|결정|심사)|허가\s*(?:예정|결정|심사)", "APPROVAL"),
        (r"출시|신제품\s*공개|제품\s*공개", "PRODUCT_LAUNCH"),
        (r"수주|공급\s*계약|대형\s*계약", "CONTRACT"),
        (r"입찰|우선협상", "TENDER"),
        (r"판결|선고", "COURT_RULING"),
        (r"임상.{0,16}(?:결과|데이터|발표)", "CLINICAL_RESULT"),
        (r"상장|IPO", "LISTING"),
        (r"합병|인수|M&A", "M_AND_A"),
        (r"착공|시설투자|설비투자|증설", "CAPEX"),
        (r"(?:정책|규제).{0,16}(?:시행|발표|결정)", "POLICY"),
    ]
    for pattern, event_type in rules:
        if re.search(pattern, normalized, re.IGNORECASE):
            return event_type
    return None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def _extract_ticker(text: str) -> str:
    match = re.search(r"\((\d{6})\)", text) or re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    return match.group(1) if match else "^KS11"


def _extract_company(title: str, ticker: str) -> str:
    clean = _clean_text(title)
    if ticker != "^KS11":
        marker = clean.find(f"({ticker})")
        if marker > 0:
            return clean[:marker].strip(" ,:-")
    first = re.split(r"[,|:·]", clean, maxsplit=1)[0].strip()
    return first[:80] or "Korea Market"


def _parse_pubdate(value: str, fallback: datetime) -> datetime:
    try:
        dt = parsedate_to_datetime(value)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return fallback


class NewsFutureCollector:
    source_name = "NEWS_FUTURE"

    def __init__(
        self,
        api_key_id: Optional[str] = None,
        api_key: Optional[str] = None,
        queries: Optional[Iterable[str]] = None,
        mock_payloads: Optional[list[dict]] = None,
        timeout: int = 10,
    ) -> None:
        self.api_key_id = api_key_id or os.getenv("NAVER_API_HUB_KEY_ID", "")
        self.api_key = api_key or os.getenv("NAVER_API_HUB_KEY", "")
        self.queries = list(queries or DEFAULT_QUERIES)
        self.mock_payloads = mock_payloads
        self.timeout = timeout
        self.session = requests.Session()

    def _fetch_payloads(self) -> list[dict]:
        if self.mock_payloads is not None:
            return self.mock_payloads
        headers = {
            "X-NCP-APIGW-API-KEY-ID": self.api_key_id,
            "X-NCP-APIGW-API-KEY": self.api_key,
        }
        payloads: list[dict] = []
        for query in self.queries:
            response = self.session.get(
                NAVER_NEWS_URL,
                headers=headers,
                params={"query": query, "display": 100, "sort": "date"},
                timeout=self.timeout,
            )
            if response.status_code != 200:
                raise ConnectionError(f"NAVER API HUB returned HTTP {response.status_code}")
            payloads.append(response.json())
        return payloads

    def collect(self, since: datetime) -> list[RawEvent]:
        started = time.time()
        if self.mock_payloads is None and (not self.api_key_id or not self.api_key):
            log_collector_run(CollectorRunLog(self.source_name, "SUCCESS", 0, time.time() - started, "missing optional NAVER API HUB credentials"))
            return []

        try:
            events: list[RawEvent] = []
            seen: set[str] = set()
            for payload in self._fetch_payloads():
                for item in payload.get("items", []):
                    title = _clean_text(item.get("title", ""))
                    description = _clean_text(item.get("description", ""))
                    combined = f"{title} {description}".strip()
                    if not combined:
                        continue

                    published = _parse_pubdate(item.get("pubDate", ""), fallback=since)
                    window = parse_future_window(combined, published.date())
                    event_type = classify_catalyst(combined)
                    if window is None or event_type is None:
                        continue
                    if window.end < published.date():
                        continue

                    source_url = item.get("originallink") or item.get("link") or ""
                    ticker = _extract_ticker(combined)
                    company = _extract_company(title, ticker)
                    uid_seed = f"{source_url}|{event_type}|{window.start.isoformat()}|{window.end.isoformat()}"
                    uid = hashlib.sha1(uid_seed.encode("utf-8")).hexdigest()
                    if uid in seen:
                        continue
                    seen.add(uid)

                    events.append(
                        RawEvent(
                            source_name=self.source_name,
                            source_kind="SECONDARY",
                            source_event_uid=uid,
                            source_url=source_url,
                            country="KR",
                            primary_ticker=ticker,
                            primary_company=company,
                            event_type=event_type,
                            event_name=title or combined[:120],
                            announced_at=published,
                            event_date=window.start,
                            date_precision=window.precision,
                            window_start=window.start,
                            window_end=window.end,
                            event_time_context="DATE_ONLY",
                            status="EXPECTED",
                            evidence_text=combined,
                            ingest_mode="AUTO",
                            raw_payload=item,
                        )
                    )

            log_collector_run(CollectorRunLog(self.source_name, "SUCCESS", len(events), time.time() - started))
            return events
        except Exception as exc:
            log_collector_run(CollectorRunLog(self.source_name, "FAILED", 0, time.time() - started, str(exc)))
            return []
