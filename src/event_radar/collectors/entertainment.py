"""Entertainment schedule and comeback event collector.

DORMANT (deregistered in scripts/collect.py, 2026-11-07): weverse.io/notice
is now a JavaScript SPA shell — the static HTML contains no notice items,
so this scraper parsed 0 events on every live run. Kept for revival
against a stable Weverse API; do not re-register against the HTML page.
"""

from __future__ import annotations
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from bs4 import BeautifulSoup
import requests
import yaml
from event_radar.models import RawEvent
from event_radar.collectors.base import CollectorRunLog, log_collector_run


DEFAULT_ARTIST_MAP = {
    "방탄소년단": {"ticker": "352820", "company": "하이브"},
    "BTS": {"ticker": "352820", "company": "하이브"},
    "뉴진스": {"ticker": "352820", "company": "하이브"},
    "NEWJEANS": {"ticker": "352820", "company": "하이브"},
    "에스파": {"ticker": "041510", "company": "에스엠"},
    "AESPA": {"ticker": "041510", "company": "에스엠"},
    "아이브": {"ticker": "035720", "company": "카카오"},
}


class EntertainmentCollector:
    """Collector for Korean official entertainment schedule announcements."""

    source_name: str = "ENTER_KR"

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

    def collect(self, since: datetime) -> list[RawEvent]:
        start_time = time.time()
        events: list[RawEvent] = []

        try:
            artist_map = DEFAULT_ARTIST_MAP.copy()
            container_sel = ".notice-item"
            title_sel = ".title"
            url = "https://weverse.io/notice"

            if self.config_path.exists():
                with open(self.config_path, mode="r", encoding="utf-8") as f:
                    all_cfg = yaml.safe_load(f) or {}
                    cfg = all_cfg.get("sources", {}).get("entertainment_kr", {})
                    url = cfg.get("url", url)
                    container_sel = cfg.get("container_selector", container_sel)
                    title_sel = cfg.get("title_selector", title_sel)
                    if "artist_map" in cfg:
                        for k, v in cfg["artist_map"].items():
                            artist_map[k] = v

            if self.mock_html is not None:
                html_text = self.mock_html
            else:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    raise ConnectionError(f"Entertainment source returned HTTP {resp.status_code}")
                html_text = resp.text

            soup = BeautifulSoup(html_text, "html.parser")
            items = soup.select(container_sel)

            for item in items:
                title_elem = item.select_one(title_sel)
                if not title_elem:
                    continue
                title_text = title_elem.get_text(strip=True)
                link_elem = item.select_one("a")
                link_url = link_elem.get("href", "") if link_elem else url

                # Find matched artist
                matched_ticker = ""
                matched_company = ""
                for artist_name, info in artist_map.items():
                    if artist_name.upper() in title_text.upper():
                        matched_ticker = info["ticker"]
                        matched_company = info["company"]
                        break

                if not matched_ticker:
                    continue

                # Extract date
                m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", title_text)
                if m:
                    ev_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                else:
                    ev_date = since.date()

                events.append(
                    RawEvent(
                        source_name=self.source_name,
                        source_kind="ORGANIZER",
                        source_url=link_url,
                        country="KR",
                        primary_ticker=matched_ticker,
                        primary_company=matched_company,
                        event_type="ENTERTAINMENT",
                        event_name=title_text,
                        announced_at=since,
                        event_date=ev_date,
                        event_time_context="DATE_ONLY",
                        status="CONFIRMED",
                        evidence_text=title_text,
                        ingest_mode="AUTO",
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
