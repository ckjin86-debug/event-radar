"""FDA / PDUFA regulatory action collector."""

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


class FdaCollector:
    """Collector for FDA and PDUFA regulatory events."""

    source_name: str = "FDA_PDUFA"

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
            cfg = {}
            if self.config_path.exists():
                with open(self.config_path, mode="r", encoding="utf-8") as f:
                    all_cfg = yaml.safe_load(f) or {}
                    cfg = all_cfg.get("sources", {}).get("fda_pdufa", {})

            url = cfg.get("url", "https://www.fda.gov/drugs/news-events-human-drugs")
            container_sel = cfg.get("container_selector", ".view-content .views-row")
            title_sel = cfg.get("title_selector", ".views-field-title a")

            if self.mock_html is not None:
                html_text = self.mock_html
            else:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    raise ConnectionError(f"FDA returned HTTP {resp.status_code}")
                html_text = resp.text

            soup = BeautifulSoup(html_text, "html.parser")
            containers = soup.select(container_sel)

            for item in containers:
                title_elem = item.select_one(title_sel)
                if not title_elem:
                    continue
                title_text = title_elem.get_text(strip=True)
                item_url = title_elem.get("href", "")
                if item_url and not item_url.startswith("http"):
                    item_url = f"https://www.fda.gov{item_url}"

                # Extract ticker e.g. (Ticker: BCRP) or (NASDAQ: BCRP)
                ticker_match = re.search(r"Ticker:\s*([A-Z0-9]+)", title_text, re.IGNORECASE)
                if not ticker_match:
                    ticker_match = re.search(r"\(([A-Z]{1,5})\)", title_text)
                ticker = ticker_match.group(1).upper() if ticker_match else ""

                # Extract date
                date_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", title_text)
                if date_match:
                    ev_date = date(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
                else:
                    ev_date = since.date()

                if ticker:
                    events.append(
                        RawEvent(
                            source_name=self.source_name,
                            source_kind="REGULATOR",
                            source_url=item_url,
                            country="US",
                            primary_ticker=ticker,
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
