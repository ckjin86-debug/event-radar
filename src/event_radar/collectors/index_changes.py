"""Index rebalance announcement and change schedule collector."""

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


class IndexChangesCollector:
    """Collector for index rebalance announcements (MSCI, KOSPI 200, S&P 500)."""

    source_name: str = "INDEX_KR"

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
            container_sel = ".notice-board tr"
            title_sel = "td.subject a"
            url = "https://global.krx.co.kr"

            if self.config_path.exists():
                with open(self.config_path, mode="r", encoding="utf-8") as f:
                    all_cfg = yaml.safe_load(f) or {}
                    cfg = all_cfg.get("sources", {}).get("index_rebalance", {})
                    url = cfg.get("url", url)
                    container_sel = cfg.get("container_selector", container_sel)
                    title_sel = cfg.get("title_selector", title_sel)

            if self.mock_html is not None:
                html_text = self.mock_html
            else:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    raise ConnectionError(f"Index source returned HTTP {resp.status_code}")
                html_text = resp.text

            soup = BeautifulSoup(html_text, "html.parser")
            items = soup.select(container_sel)

            for item in items:
                title_elem = item.select_one(title_sel)
                if not title_elem:
                    continue
                title_text = title_elem.get_text(strip=True)
                if "지수" not in title_text and "변경" not in title_text and "INDEX" not in title_text.upper():
                    continue

                link_url = title_elem.get("href", url)
                if link_url and not link_url.startswith("http"):
                    link_url = f"https://global.krx.co.kr{link_url}"

                m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", title_text)
                if m:
                    ev_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                else:
                    ev_date = since.date()

                events.append(
                    RawEvent(
                        source_name=self.source_name,
                        source_kind="EXCHANGE",
                        source_url=link_url,
                        country="KR",
                        primary_ticker="069500",  # KODEX 200 / KRX Index representative
                        primary_company="KRX 지수산출기관",
                        event_type="INDEX_REBALANCE",
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
