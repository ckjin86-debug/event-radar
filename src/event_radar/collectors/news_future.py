"""Future-oriented Korean market event discovery from NAVER API HUB news search."""

from __future__ import annotations

import calendar
import hashlib
import html
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "다음달 가동",
    "내년 가동",
    "내달 착공",
    "다음달 착공",
    "내년 착공",
    "연내 승인",
    "다음달 승인",
    "내년 승인",
    "FDA 승인 예정",
    "임상 결과 예정",
    "임상 발표 예정",
    "정책 시행 예정",
    "정책 발표 예정",
    "규제 시행 예정",
    "수주 발표 예정",
    "공급 계약 예정",
    "입찰 예정",
    "우선협상 예정",
    "원전 입찰 예정",
    "원전 수주 예정",
    "경영권 분쟁 예정",
    "임시주총 예정",
    "주총 표대결 예정",
    "선고 예정",
    "판결 예정",
    "인수 예정",
    "합병 예정",
    "대선 경선 예정",
    "총선 일정",
    "지방선거 예정",
    "후보 확정 예정",
    "신제품 출시 예정",
    "신작 출시 예정",
    "시설투자 예정",
    "증설 예정",
]

BROAD_WINDOW_EVENT_TYPES = {
    "PLANT_OPERATION",
    "APPROVAL",
    "CLINICAL_RESULT",
    "M_AND_A",
    "CAPEX",
    "CAPEX_FINANCING",
    "POLICY",
    "COURT_RULING",
    "TENDER",
    "CONTROL_DISPUTE",
    "ELECTION",
}

MARKET_WIDE_EVENT_TYPES = {"POLICY", "COURT_RULING", "TENDER", "ELECTION"}

EVENT_PATTERNS: dict[str, str] = {
    "PLANT_OPERATION": r"(?:상업\s*가동|공장.{0,12}가동|라인.{0,12}가동|생산.{0,8}가동)(?!\s*(?:률|율|물량))",
    "APPROVAL": r"FDA.{0,12}(?:승인|허가)|승인\s*(?:예정|결정|심사)|허가\s*(?:예정|결정|심사)",
    "PRODUCT_LAUNCH": (
        r"(?:신제품|신작|신규\s*(?:제품|서비스|플랫폼)).{0,40}(?:출시|공개)"
        r"|(?:정식|글로벌)\s*(?:정식\s*)?출시"
        r"|(?:제품|서비스|플랫폼).{0,24}(?:출시|공개)"
    ),
    "CONTRACT": r"수주|공급\s*계약|대형\s*계약",
    "TENDER": r"입찰|우선협상",
    "COURT_RULING": r"판결|선고",
    "CLINICAL_RESULT": r"임상.{0,16}(?:결과|데이터|발표)",
    "M_AND_A": r"합병|인수(?!권)|M&A",
    "CAPEX": r"착공|시설투자|설비투자|증설",
    "POLICY": r"(?:정책|규제).{0,16}(?:시행|발표|결정)",
    "CONTROL_DISPUTE": r"경영권.{0,16}(?:분쟁|갈등|표대결|주총)|(?:임시)?주총.{0,16}(?:경영권|표대결)|가처분.{0,16}(?:경영권|의결권)",
    "ELECTION": r"대선|총선|지방선거|경선|후보\s*(?:등록|확정|선출)",
    "CAPEX_FINANCING": r"유상증자|시설투자|설비투자|시설자금|공장|증설|CAPEX",
}

LOW_QUALITY_COMPANY_MARKERS = (
    "뉴스브리핑",
    "신상브리핑",
    "유통레이더",
    "똑똑한",
    "현장르포",
    "굿모닝",
    "아시아라운드업",
    "게임 게시판",
)

# Headlines whose subject is a completed evaluation, award, casting, or a
# price-move roundup are not scheduled catalysts — even when the article body
# incidentally mentions another company's clinical trial, contract, or plan.
# The headline is the article's subject, so a non-event headline vetoes the
# whole item (collector, pipeline repair, and export all share this check).
NON_EVENT_HEADLINE_PATTERNS = (
    r"ESG[^.]{0,24}(?:평가|등급|지수)",  # ESG 평가/등급 결과 기사
    r"평가서",  # 평가서·등급 획득 류
    r"(?:수상|어워즈|브랜드\s*대상)",  # 수상/선정 홍보 기사
    r"(?:모델\s*(?:발탁|선정)|홍보대사|앰버서더)",  # 모델 발탁 홍보 기사
    r"등\s*\d+\s*개\s*종목",  # "N개 종목 급등" 시황 라운드업
)

_NON_EVENT_HEADLINE_RE = re.compile("|".join(NON_EVENT_HEADLINE_PATTERNS))


def _headline_of(text: str) -> str:
    """Return the headline segment of a combined title+description text."""
    cleaned = _clean_text(text)
    head = re.split(r"\.\s", cleaned, maxsplit=1)[0]
    return head[:160]


def is_non_event_headline(text: str) -> bool:
    """True when the headline subject is an evaluation/award/promo story."""
    headline = _headline_of(text)
    if _NON_EVENT_HEADLINE_RE.search(headline):
        return True
    # Multi-company price-move roundups ("A·B 등 급등") are market recaps,
    # not scheduled events for any single company in the headline.
    if "·" in headline and re.search(r"급등|급락|상한가|하한가", headline):
        return True
    return False


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

    # Match the complete expression, including its year/relative context. A past
    # month is historical evidence, never an implicit appointment for next year.
    pattern = re.compile(
        r"(?P<context>20\d{2}\s*년|내년|올해|금년|작년|지난해|지난|오는)?\s*"
        r"(?:(?P<month>1[0-2]|0?[1-9])\s*월(?:\s*(?P<day>3[01]|[12]?\d)\s*일)?"
        r"|(?P<relative>내달|다음달|이달|이번\s*달)(?:\s*(?P<rday>3[01]|[12]?\d)\s*일)?"
        r"|(?P<quarter>[1-4])\s*분기|(?P<half>상반기|하반기)"
        r"|(?P<cday>3[01]|[12]?\d)\s*일)"
    )
    for m in pattern.finditer(normalized):
        if m.start() > 0 and normalized[m.start()].isdigit() and normalized[m.start() - 1].isdigit():
            continue
        context = (m.group("context") or "").strip()
        if context in {"작년", "지난해", "지난"}:
            continue
        year = reference_date.year
        if context == "내년":
            year += 1
        elif context.startswith("20"):
            year = int(context[:4])
        # Do not interpret a bare day (clinical phase counts etc.) as a date.
        if m.group("cday") and context != "오는":
            continue
        try:
            if m.group("month"):
                month = int(m.group("month"))
                if m.group("day"):
                    start = end = date(year, month, int(m.group("day")))
                    precision = "EXACT_DATE"
                else:
                    start, end = _month_bounds(year, month)
                    precision = "MONTH"
            elif m.group("relative"):
                relative = m.group("relative").replace(" ", "")
                year, month = _next_month(reference_date) if relative in {"내달", "다음달"} else (year, reference_date.month)
                if m.group("rday"):
                    start = end = date(year, month, int(m.group("rday")))
                    precision = "EXACT_DATE"
                else:
                    start, end = _month_bounds(year, month)
                    start = max(start, reference_date)
                    precision = "MONTH"
            elif m.group("quarter"):
                month = (int(m.group("quarter")) - 1) * 3 + 1
                start = date(year, month, 1)
                end = _month_bounds(year, month + 2)[1]
                precision = "QUARTER"
            elif m.group("half"):
                month = 1 if m.group("half") == "상반기" else 7
                start = date(year, month, 1)
                end = _month_bounds(year, month + 5)[1]
                precision = "HALF_YEAR"
            else:
                day = int(m.group("cday"))
                year, month = reference_date.year, reference_date.month
                start = date(year, month, day)
                if start < reference_date:
                    year, month = _next_month(reference_date)
                    start = date(year, month, day)
                end = start
                precision = "EXACT_DATE"
        except ValueError:
            continue
        if end >= reference_date:
            return FutureWindow(precision, start, end, m.group(0).strip())

    # A year-only expression must not override a more specific historical date.
    if re.search(r"\d\s*월|분기|상반기|하반기", normalized):
        return None
    m = re.search(r"내년|연내|20\d{2}\s*년", normalized)
    if m:
        year = reference_date.year + 1 if m.group(0) == "내년" else reference_date.year
        if m.group(0).startswith("20"):
            year = int(m.group(0)[:4])
        if year >= reference_date.year:
            return FutureWindow("YEAR", max(date(year, 1, 1), reference_date), date(year, 12, 31), m.group(0))
    return None


def classify_catalyst(text: str) -> Optional[str]:
    """Return a market-relevant event type or None for low-signal text."""
    normalized = html.unescape(re.sub(r"<[^>]+>", " ", text))

    if "유상증자" in normalized:
        if re.search(r"시설투자|설비투자|시설자금|공장|증설|CAPEX", normalized, re.IGNORECASE):
            return "CAPEX_FINANCING"
        return None

    if re.search(r"상장|IPO", normalized, re.IGNORECASE):
        return None

    for event_type, pattern in EVENT_PATTERNS.items():
        if event_type == "CAPEX_FINANCING":
            continue
        if re.search(pattern, normalized, re.IGNORECASE):
            return event_type
    return None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def _extract_ticker(text: str) -> str:
    match = re.search(r"\((\d{6})\)", text) or re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    return match.group(1) if match else ""


def _extract_company(title: str, ticker: str) -> str:
    clean = _clean_text(title)
    clean = re.sub(r"^\[[^\]]+\]\s*", "", clean)
    if ticker:
        marker = clean.find(f"({ticker})")
        if marker > 0:
            return clean[:marker].strip(" ,:-")
    first = re.split(r"[,|:·…]", clean, maxsplit=1)[0].strip(" ,:-'\"“”‘’")
    return first[:80] or "Korea Market"


def _parse_pubdate(value: str, fallback: datetime) -> datetime:
    try:
        dt = parsedate_to_datetime(value)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return fallback


def _is_actionable_window(window: FutureWindow, event_type: str) -> bool:
    if event_type == "PRODUCT_LAUNCH":
        return window.precision == "EXACT_DATE"
    if window.precision in {"YEAR", "HALF_YEAR", "QUARTER"}:
        return event_type in BROAD_WINDOW_EVENT_TYPES
    return True


def _is_temporally_linked(text: str, window: FutureWindow, event_type: str) -> bool:
    pattern = EVENT_PATTERNS.get(event_type)
    if not pattern or not window.matched_text:
        return False

    normalized = _clean_text(text)
    clauses = [part.strip() for part in re.split(r"[.!?。！？]+", normalized) if part.strip()]
    matched = _clean_text(window.matched_text)
    for clause in clauses:
        if matched in clause and re.search(pattern, clause, re.IGNORECASE):
            return True
    return False


def extract_future_catalyst(text: str, reference_date: date) -> tuple[FutureWindow, str] | None:
    """Select a dated catalyst in the same clause, ignoring historical background."""
    if is_non_event_headline(text):
        return None
    clauses = re.split(r"(?<!\d)[.!?。！？]+(?!\d)", _clean_text(text))
    for clause in clauses:
        if re.search(r"일정\s*미정|날짜\s*미정|시기\s*미정", clause):
            continue
        # Retrospective reports and conditional commentary are not future schedules.
        if re.search(r"(?:체결|선고|출시|가동|발표|시행|착공|완료|개최|공개|인수)(?:했|했다|됐다|한 바|한 것으로|한 뒤|한 데)|이미.{0,12}(?:가동|출시)|가능성|검토 중|계획\s*없", clause):
            continue
        if classify_catalyst(clause) is None:
            continue
        # Enumerate every future expression rather than assigning the first date
        # to an unrelated action later in the sentence.
        remaining = clause
        windows = []
        while True:
            window = parse_future_window(remaining, reference_date)
            if window is None:
                break
            start = remaining.find(window.matched_text)
            if start < 0:
                break
            end = start + len(window.matched_text)
            # A date that merely ends a stated period ("계약 기간은 2031년
            # 12월 31일까지") is a maturity/expiry bound, not the date of a
            # future catalyst, so it can never anchor an event window.
            preceding = clause[max(0, start - 16):start]
            if not re.search(r"(?:기간|만기|종료일)\s*(?:은|는)?\s*$", preceding):
                windows.append((start, end, window))
            remaining = remaining[:start] + " " * (end - start) + remaining[end:]
        candidates = []
        for kind, pattern in EVENT_PATTERNS.items():
            if kind == "CAPEX_FINANCING" and "유상증자" not in clause:
                continue
            for catalyst in re.finditer(pattern, clause, re.IGNORECASE):
                for start, end, window in windows:
                    if not _is_actionable_window(window, kind):
                        continue
                    gap = max(0, catalyst.start() - end, start - catalyst.end())
                    if gap > 48:
                        continue
                    left, right = sorted((end, catalyst.start()))
                    if any(left <= other_start < right for other_start, _, other_window in windows if other_window is not window):
                        continue
                    candidates.append((gap, start, kind, window))
        if candidates:
            _, _, kind, window = min(candidates, key=lambda item: (item[0], item[1]))
            return window, kind
    return None


def is_news_digest(title: str) -> bool:
    return bool(re.search(r"사설|칼럼|기고|브리프|브리핑|알공|인물탐구|Who Is|바이오스냅", title, re.IGNORECASE))


def _is_low_quality_company(company: str, event_type: str) -> bool:
    if event_type in MARKET_WIDE_EVENT_TYPES:
        return False
    if any(marker in company for marker in LOW_QUALITY_COMPANY_MARKERS):
        return True
    if len(company) > 60:
        return True
    return False


def _cluster_company_key(company: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", company).lower()


class NewsFutureCollector:
    source_name = "NEWS_FUTURE"

    def __init__(
        self,
        api_key_id: Optional[str] = None,
        api_key: Optional[str] = None,
        queries: Optional[Iterable[str]] = None,
        mock_payloads: Optional[list[dict]] = None,
        timeout: int = 10,
        max_workers: int = 8,
    ) -> None:
        self.api_key_id = api_key_id or os.getenv("NAVER_API_HUB_KEY_ID", "")
        self.api_key = api_key or os.getenv("NAVER_API_HUB_KEY", "")
        self.queries = list(queries or DEFAULT_QUERIES)
        self.mock_payloads = mock_payloads
        self.timeout = timeout
        self.max_workers = max(1, min(12, int(max_workers)))

    def _fetch_one(self, query: str, headers: dict[str, str]) -> dict | None:
        try:
            response = requests.get(
                NAVER_NEWS_URL,
                headers=headers,
                params={"query": query, "display": 100, "sort": "date"},
                timeout=self.timeout,
            )
            if response.status_code != 200:
                return None
            return response.json()
        except Exception:
            return None

    def _fetch_payloads(self) -> list[dict]:
        if self.mock_payloads is not None:
            return self.mock_payloads
        if not self.queries:
            return []

        headers = {
            "X-NCP-APIGW-API-KEY-ID": self.api_key_id,
            "X-NCP-APIGW-API-KEY": self.api_key,
        }
        results: list[dict | None] = [None] * len(self.queries)
        workers = min(self.max_workers, len(self.queries))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(self._fetch_one, query, headers): index
                for index, query in enumerate(self.queries)
            }
            for future in as_completed(future_map):
                index = future_map[future]
                try:
                    results[index] = future.result()
                except Exception:
                    results[index] = None

        payloads = [payload for payload in results if payload is not None]
        if not payloads and self.queries:
            raise ConnectionError("NAVER API HUB queries all failed")
        return payloads

    def collect(self, since: datetime) -> list[RawEvent]:
        started = time.time()
        if self.mock_payloads is None and (not self.api_key_id or not self.api_key):
            log_collector_run(
                CollectorRunLog(
                    self.source_name,
                    "SUCCESS",
                    0,
                    time.time() - started,
                    "missing optional NAVER API HUB credentials",
                )
            )
            return []

        try:
            clusters: dict[str, dict] = {}
            for payload in self._fetch_payloads():
                for item in payload.get("items", []):
                    title = _clean_text(item.get("title", ""))
                    description = _clean_text(item.get("description", ""))
                    combined = f"{title}. {description}".strip()
                    if not title:
                        continue
                    if is_news_digest(title):
                        continue

                    published = _parse_pubdate(item.get("pubDate", ""), fallback=since)
                    if published < since:
                        continue
                    candidate = extract_future_catalyst(combined, published.date())
                    if candidate is None:
                        continue
                    window, event_type = candidate

                    ticker = _extract_ticker(combined)
                    company = _extract_company(title, ticker)
                    if _is_low_quality_company(company, event_type):
                        continue

                    source_url = item.get("originallink") or item.get("link") or ""
                    cluster_key = "|".join(
                        [
                            _cluster_company_key(company),
                            event_type,
                            window.start.isoformat(),
                            window.end.isoformat(),
                        ]
                    )
                    existing = clusters.get(cluster_key)
                    if existing is None:
                        clusters[cluster_key] = {
                            "title": title,
                            "combined": combined,
                            "published": published,
                            "window": window,
                            "event_type": event_type,
                            "ticker": ticker,
                            "company": company,
                            "source_url": source_url,
                            "item": item,
                            "source_urls": [source_url] if source_url else [],
                            "article_count": 1,
                        }
                        continue

                    existing["article_count"] += 1
                    if source_url and source_url not in existing["source_urls"]:
                        existing["source_urls"].append(source_url)
                    if ticker and not existing["ticker"]:
                        existing.update(
                            {
                                "title": title,
                                "combined": combined,
                                "published": published,
                                "ticker": ticker,
                                "company": company,
                                "source_url": source_url,
                                "item": item,
                            }
                        )

            events: list[RawEvent] = []
            for cluster_key, cluster in clusters.items():
                uid = hashlib.sha1(cluster_key.encode("utf-8")).hexdigest()
                raw_payload = dict(cluster["item"])
                raw_payload["cluster_article_count"] = cluster["article_count"]
                raw_payload["cluster_source_urls"] = cluster["source_urls"][:20]
                window = cluster["window"]
                events.append(
                    RawEvent(
                        source_name=self.source_name,
                        source_kind="SECONDARY",
                        source_event_uid=uid,
                        source_url=cluster["source_url"],
                        country="KR",
                        primary_ticker=cluster["ticker"],
                        primary_company=cluster["company"],
                        event_type=cluster["event_type"],
                        event_name=cluster["title"] or cluster["combined"][:120],
                        announced_at=cluster["published"],
                        event_date=window.start,
                        date_precision=window.precision,
                        window_start=window.start,
                        window_end=window.end,
                        event_time_context="DATE_ONLY",
                        status="EXPECTED",
                        evidence_text=cluster["combined"],
                        ingest_mode="AUTO",
                        raw_payload=raw_payload,
                    )
                )

            events.sort(key=lambda event: (event.event_date, event.primary_company, event.event_type))
            log_collector_run(CollectorRunLog(self.source_name, "SUCCESS", len(events), time.time() - started))
            return events
        except Exception as exc:
            log_collector_run(CollectorRunLog(self.source_name, "FAILED", 0, time.time() - started, str(exc)))
            return []
