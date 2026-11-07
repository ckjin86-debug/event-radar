"""PILOT — Scrapling-based variant of the Inven games calendar collector.

This module mirrors :class:`event_radar.collectors.games.GamesCollector`
(same source, same config, same game map, same ``RawEvent`` output schema)
but parses the page with Scrapling's ``Adaptor`` instead of BeautifulSoup.

Why: the legacy collector hard-codes CSS classes (``.calendar__item`` etc.).
Inven already retired one page layout (``/schedule`` -> ``/webzine/calendar``);
when the class names change again, the BeautifulSoup selectors silently
return nothing. Scrapling can *relocate* elements: selections made with
``auto_save=True`` store a structural fingerprint of each element, and a
later parse with ``adaptive=True`` finds the same elements by similarity
even when the original selector no longer matches.

Pilot scope / caveats:
- Not wired into the collector registry; nothing in production uses this yet.
- ``scrapling`` is an optional dependency for this pilot only (not in
  ``pyproject.toml`` dependencies).
- Date-resolution semantics intentionally duplicate
  ``GamesCollector._parse_event_date`` so the two collectors stay
  independent; if this pilot is adopted, the shared logic should be
  factored out instead of copied.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests
import yaml
from scrapling.parser import Adaptor

from event_radar.models import RawEvent
from event_radar.collectors.base import CollectorRunLog, log_collector_run
from event_radar.collectors.games import DEFAULT_GAME_MAP


class GamesScraplingCollector:
    """Scrapling/adaptive variant of the Inven game calendar collector."""

    source_name: str = "GAMES_RELEASE"

    def __init__(
        self,
        config_path: Path | str = "config/site_registry.yaml",
        mock_html: Optional[str] = None,
        timeout: int = 10,
        storage_file: Optional[str] = None,
        adaptive: bool = True,
    ):
        self.config_path = Path(config_path)
        self.mock_html = mock_html
        self.timeout = timeout
        # Where Scrapling keeps element fingerprints for relocation.
        # None -> Scrapling's library default location.
        self.storage_file = storage_file
        self.adaptive = adaptive
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EventRadar/1.0"
        })

    # -- Scrapling helpers -------------------------------------------------

    def _select(self, node, selector: str):
        """Select with fingerprint saving; relocate adaptively if broken.

        A normal hit also refreshes the stored fingerprint (``auto_save``).
        Only when the selector matches nothing do we fall back to adaptive
        relocation against previously saved fingerprints.
        """
        if not selector:
            return []
        found = node.css(selector, auto_save=True)
        if found:
            return found
        if self.adaptive:
            return node.css(selector, adaptive=True)
        return found

    @staticmethod
    def _text(node) -> str:
        return node.get_all_text(strip=True) if node is not None else ""

    # -- Date logic (same semantics as GamesCollector._parse_event_date) ---

    @staticmethod
    def _resolve_date(
        title_text: str,
        date_text: str,
        page_year: int,
        page_month: int,
        since: datetime,
    ) -> date:
        m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", title_text)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass

        m = re.search(r"(\d{1,2})/(\d{1,2})", date_text or title_text)
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

    # -- Main entry point ---------------------------------------------------

    def collect(self, since: datetime) -> list[RawEvent]:
        start_time = time.time()
        events: list[RawEvent] = []

        try:
            game_map = DEFAULT_GAME_MAP.copy()
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

            page_year, page_month = since.year, since.month
            ym = re.search(r"/calendar/(\d{4})/(\d{1,2})", page_url)
            if ym:
                page_year, page_month = int(ym.group(1)), int(ym.group(2))

            storage_args = None
            if self.storage_file:
                storage_args = {"storage_file": self.storage_file, "url": page_url}
            # NOTE: Scrapling 0.5.x ignores auto_save/adaptive selection
            # unless the parser itself is initialised with adaptive=True.
            page = Adaptor(
                content=html_text,
                url=page_url,
                adaptive=True,
                storage_args=storage_args,
            )

            items = self._select(page, container_sel)

            for item in items:
                title_hits = self._select(item, title_sel)
                if not title_hits:
                    continue
                title_text = re.sub(r"\s*새창\s*$", "", self._text(title_hits[0]))

                link_hits = item.css("a")
                link_url = link_hits[0].attrib.get("href", "") if link_hits else url
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

                date_hits = self._select(item, date_sel)
                date_text = self._text(date_hits[0]) if date_hits else title_text
                ev_date = self._resolve_date(
                    title_text, date_text, page_year, page_month, since
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
