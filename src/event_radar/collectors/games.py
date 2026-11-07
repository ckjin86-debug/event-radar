"""Game release and major update collector.

Source: Inven game calendar (https://www.inven.co.kr/webzine/calendar).
The old /schedule page was retired (HTTP 404); the calendar renders
items server-side with month/day-only dates anchored to the page month.
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


DEFAULT_GAME_MAP = {
    "INZOI": {"ticker": "259960", "company": "크래프톤"},
    "인조이": {"ticker": "259960", "company": "크래프톤"},
    "붉은사막": {"ticker": "263750", "company": "펄어비스"},
    "CRIMSON DESERT": {"ticker": "263750", "company": "펄어비스"},
    "TL": {"ticker": "036570", "company": "엔씨소프트"},
    "스텔라 블레이드": {"ticker": "462870", "company": "시프트업"},
    "STELLAR BLADE": {"ticker": "462870", "company": "시프트업"},
}


class GamesCollector:
    """Collector for major game launches and updates."""

    source_name: str = "GAMES_RELEASE"

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

    @staticmethod
    def _parse_event_date(
        item,
        title_text: str,
        date_sel: str,
        page_year: int,
        page_month: int,
        since: datetime,
    ) -> date:
        """Resolve an item's date.

        Full dates (YYYY.MM.DD) win when present in the title. The Inven
        calendar instead renders month/day only ("11/02(월)" or a range
        "10/16(금)~11/15(일)"), so anchor those to the page's year-month,
        rolling the year when an item spills across a year boundary.
        """
        m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", title_text)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

        date_elem = item.select_one(date_sel) if date_sel else None
        date_text = date_elem.get_text(strip=True) if date_elem else title_text
        m = re.search(r"(\d{1,2})/(\d{1,2})", date_text)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = page_year
            if month - page_month >= 6:
                year -= 1
            elif page_month - month >= 6:
                year += 1
            try:
                return date(year, month, day)
            except ValueError:
                pass

        return since.date()

    def collect(self, since: datetime) -> list[RawEvent]:
        start_time = time.time()
        events: list[RawEvent] = []

        try:
            game_map = DEFAULT_GAME_MAP.copy()
            # Inven retired /schedule (404 since 2026); the release calendar
            # now lives under /webzine/calendar with .calendar__* markup and
            # month/day-only dates (the year/month come from the page URL).
            container_sel = ".calendar__item"
            title_sel = ".calendar__title"
            date_sel = ".calendar__date"
            url = "https://www.inven.co.kr/webzine/calendar"

            if self.config_path.exists():
                with open(self.config_path, mode="r", encoding="utf-8") as f:
                    all_cfg = yaml.safe_load(f) or {}
                    cfg = all_cfg.get("sources", {}).get("games_kr", {})
                    url = cfg.get("url", url)
                    container_sel = cfg.get("container_selector", container_sel)
                    title_sel = cfg.get("title_selector", title_sel)
                    date_sel = cfg.get("date_selector", date_sel)
                    if "game_map" in cfg:
                        for k, v in cfg["game_map"].items():
                            game_map[k] = v

            page_url = url
            if self.mock_html is not None:
                html_text = self.mock_html
            else:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    raise ConnectionError(f"Games source returned HTTP {resp.status_code}")
                html_text = resp.text
                page_url = resp.url or url

            # The calendar page is scoped to one year-month (in its URL);
            # item dates carry only month/day, so anchor them to that page.
            page_year, page_month = since.year, since.month
            ym = re.search(r"/calendar/(\d{4})/(\d{1,2})", page_url)
            if ym:
                page_year, page_month = int(ym.group(1)), int(ym.group(2))

            soup = BeautifulSoup(html_text, "html.parser")
            items = soup.select(container_sel)

            for item in items:
                title_elem = item.select_one(title_sel)
                if not title_elem:
                    continue
                title_text = re.sub(r"\s*새창\s*$", "", title_elem.get_text(strip=True))
                link_elem = item.select_one("a")
                link_url = link_elem.get("href", "") if link_elem else url
                if link_url and link_url.startswith("/"):
                    link_url = f"https://www.inven.co.kr{link_url}"

                matched_ticker = ""
                matched_company = ""
                for g_title, info in game_map.items():
                    if g_title.upper() in title_text.upper():
                        matched_ticker = info["ticker"]
                        matched_company = info["company"]
                        break

                if not matched_ticker:
                    continue

                ev_date = self._parse_event_date(
                    item, title_text, date_sel, page_year, page_month, since
                )

                events.append(
                    RawEvent(
                        source_name=self.source_name,
                        source_kind="COMPANY",
                        source_url=link_url,
                        country="KR",
                        primary_ticker=matched_ticker,
                        primary_company=matched_company,
                        event_type="GAME_RELEASE",
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
