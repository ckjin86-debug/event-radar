"""DART (Data Analysis, Retrieval and Transfer System) corporate action collector."""

from __future__ import annotations
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import requests
from event_radar.models import RawEvent
from event_radar.collectors.base import CollectorRunLog, log_collector_run


DART_EVENT_MAP = [
    ("무상증자", "BONUS_ISSUE"),
    ("유상증자", "RIGHTS_ISSUE"),
    ("주식분할", "STOCK_SPLIT"),
    ("액면분할", "STOCK_SPLIT"),
    ("전환사채", "CONVERTIBLE_LISTING"),
    ("신주인수권", "CONVERTIBLE_LISTING"),
    ("CB", "CONVERTIBLE_LISTING"),
    ("보호예수", "LOCKUP_EXPIRY"),
    ("의무보유", "LOCKUP_EXPIRY"),
    ("잠정실적", "EARNINGS"),
    ("영업실적", "EARNINGS"),
]


class DartCollector:
    """Collector for Korean official corporate disclosures from DART."""

    source_name: str = "DART"

    def __init__(
        self,
        api_key: Optional[str] = None,
        fixture_path: Optional[Path | str] = None,
        timeout: int = 10,
    ):
        self.api_key = api_key or os.getenv("DART_API_KEY", "")
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EventRadar/1.0"
        })

    def _classify_event_type(self, title: str) -> Optional[str]:
        for kw, ev_type in DART_EVENT_MAP:
            if kw in title:
                return ev_type
        return None

    def _extract_date(self, text: str, default_date: date) -> date:
        # Match YYYY-MM-DD or YYYY.MM.DD or YYYY년 MM월 DD일
        m = re.search(r"(\d{4})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})", text)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        return default_date

    def collect(self, since: datetime) -> list[RawEvent]:
        """Collect corporate action disclosures."""
        start_time = time.time()
        events: list[RawEvent] = []

        try:
            # 1. Use local fixture if provided
            if self.fixture_path and self.fixture_path.exists():
                with open(self.fixture_path, mode="r", encoding="utf-8") as f:
                    data = json.load(f)
                items = data.get("list", [])
            elif self.api_key:
                # OpenDART list API query
                bgn_de = since.strftime("%Y%m%d")
                end_de = datetime.now().strftime("%Y%m%d")
                url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={self.api_key}&bgn_de={bgn_de}&end_de={end_de}&pblntf_ty=B&page_count=100"
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    raise ConnectionError(f"DART HTTP {resp.status_code}")
                data = resp.json()
                items = data.get("list", [])
            else:
                # Neither fixture nor API key: return empty gracefully
                items = []

            for item in items:
                report_nm = item.get("report_nm", "")
                ev_type = self._classify_event_type(report_nm)
                if not ev_type:
                    continue

                ticker = item.get("stock_code", "").strip()
                if not ticker:
                    continue

                rcept_no = item.get("rcept_no", "").strip()
                rcept_dt_str = item.get("rcept_dt", "").strip()
                try:
                    ann_date = datetime.strptime(rcept_dt_str, "%Y%m%d") if len(rcept_dt_str) == 8 else since
                except ValueError:
                    ann_date = since

                # Target event date from disclosure details or item
                if "event_date" in item:
                    ev_date = date.fromisoformat(item["event_date"].strip()[:10])
                else:
                    details = item.get("details", "")
                    ev_date = self._extract_date(details, default_date=ann_date.date())

                url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else ""

                events.append(
                    RawEvent(
                        source_name="DART",
                        source_kind="REGULATOR",
                        source_event_uid=rcept_no or None,
                        source_url=url,
                        country="KR",
                        primary_ticker=ticker,
                        primary_company=item.get("corp_name", "").strip(),
                        event_type=ev_type,
                        event_name=f"{item.get('corp_name', '')} {report_nm}".strip(),
                        announced_at=ann_date,
                        event_date=ev_date,
                        event_time_context="DATE_ONLY",
                        status="CONFIRMED",
                        evidence_text=item.get("details", report_nm).strip(),
                        ingest_mode="AUTO",
                        raw_payload=item,
                    )
                )

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

        except Exception as e:
            duration = time.time() - start_time
            log_collector_run(
                CollectorRunLog(
                    source_name=self.source_name,
                    status="FAILED",
                    items_count=0,
                    duration_sec=duration,
                    error_message=str(e),
                )
            )
            return []
