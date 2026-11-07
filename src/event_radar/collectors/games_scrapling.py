"""Scrapling-based Inven games calendar collector (production).

This is the production implementation of the GAMES_RELEASE source. It
mirrors the legacy BeautifulSoup collector
(:class:`event_radar.collectors.games.GamesCollector`, kept for fallback /
comparison) — same source, same config, same game map, same ``RawEvent``
output schema — but parses the page with Scrapling's ``Adaptor``.

Why: the legacy collector hard-codes CSS classes (``.calendar__item``
etc.). Inven already retired one page layout (``/schedule`` ->
``/webzine/calendar``); when the class names change again, the
BeautifulSoup selectors silently return nothing. Scrapling can *relocate*
elements: selections made with ``auto_save=True`` store a structural
fingerprint of each element, and a later parse with ``adaptive=True``
finds the same elements by similarity even when the original selector no
longer matches.

Operational contract (adopted 2026-11-07 after the pilot on branch
``pilot/scrapling-games``):

- Fingerprints persist across runs in a SQLite file under
  ``data/fingerprints/`` (see ``DEFAULT_FINGERPRINT_PATH``). The
  collection workflow commits ``data/`` after every run, so the store
  survives GitHub Actions' ephemeral runners. Without a persisted store
  the adaptive relocation cannot work (cold start = no recovery).
- Recovery is never silent: when a selector only matches through adaptive
  relocation, the run is logged with an ``ADAPTIVE_RECOVERY:`` note in
  ``data/logs/collector_runs.csv`` and the selectors are exposed on
  :attr:`GamesScraplingCollector.recovered_selectors`, so a markup change
  is visible in the run history instead of being masked.
- Date resolution is shared with the legacy collector via
  :func:`event_radar.collectors.games.resolve_event_date`.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import yaml
from scrapling.parser import Adaptor

from event_radar.models import RawEvent
from event_radar.collectors.base import CollectorRunLog, log_collector_run
from event_radar.collectors.games import DEFAULT_GAME_MAP, resolve_event_date


DEFAULT_FINGERPRINT_PATH = "data/fingerprints/games_scrapling.db"


class GamesScraplingCollector:
    """Scrapling/adaptive collector for the Inven game calendar."""

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
        # None -> the repo-persisted default under data/fingerprints/,
        # which the collection workflow commits alongside the datasets.
        self.storage_file = storage_file or DEFAULT_FINGERPRINT_PATH
        self.adaptive = adaptive
        # Selectors that only matched via adaptive relocation in the most
        # recent collect() run (empty when the primary selectors worked).
        self.recovered_selectors: list[str] = []
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EventRadar/1.0"
        })

    # -- Scrapling helpers -------------------------------------------------

    def _select(self, node, selector: str):
        """Select with fingerprint saving; relocate adaptively if broken.

        A normal hit also refreshes the stored fingerprint (``auto_save``).
        Only when the selector matches nothing do we fall back to adaptive
        relocation against previously saved fingerprints — and record it,
        so the recovery is explicit in the run log rather than silent.
        """
        if not selector:
            return []
        found = node.css(selector, auto_save=True)
        if found:
            return found
        if self.adaptive:
            relocated = node.css(selector, adaptive=True)
            if relocated and selector not in self.recovered_selectors:
                self.recovered_selectors.append(selector)
            return relocated
        return found

    @staticmethod
    def _text(node) -> str:
        return node.get_all_text(strip=True) if node is not None else ""

    # -- Main entry point ---------------------------------------------------

    def collect(self, since: datetime) -> list[RawEvent]:
        start_time = time.time()
        events: list[RawEvent] = []
        self.recovered_selectors = []

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

            # The fingerprint store must live in a directory that exists;
            # Scrapling creates the SQLite file but not its parents.
            storage_path = Path(self.storage_file)
            if storage_path.parent and not storage_path.parent.exists():
                storage_path.parent.mkdir(parents=True, exist_ok=True)
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
                ev_date = resolve_event_date(
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
            recovery_note = ""
            if self.recovered_selectors:
                recovery_note = (
                    "ADAPTIVE_RECOVERY: selectors relocated via stored "
                    f"fingerprints: {', '.join(sorted(self.recovered_selectors))}"
                )
                print(f"[GAMES_RELEASE] {recovery_note}")
            log_collector_run(
                CollectorRunLog(
                    source_name=self.source_name,
                    status="SUCCESS",
                    items_count=len(events),
                    duration_sec=duration,
                    error_message=recovery_note,
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
