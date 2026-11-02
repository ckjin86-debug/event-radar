"""SEC EDGAR collector for US corporate actions, earnings 8-Ks, and splits."""

from __future__ import annotations
import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import requests
from event_radar.models import RawEvent
from event_radar.collectors.base import CollectorRunLog, log_collector_run


SEC_DEFAULT_USER_AGENT = "EventRadarAdmin admin@eventradar.org"


class SecCollector:
    """Collector for US corporate filings from SEC EDGAR."""

    source_name: str = "SEC"

    def __init__(
        self,
        fixture_path: Optional[Path | str] = None,
        user_agent: str = SEC_DEFAULT_USER_AGENT,
        timeout: int = 10,
    ):
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
        })

    def _determine_event_type(self, form: str, items: str, desc: str) -> Optional[str]:
        combined = f"{form} {items} {desc}".upper()
        if "2.02" in items or "EARNINGS" in combined:
            return "EARNINGS"
        if "3.03" in items or "SPLIT" in combined:
            return "STOCK_SPLIT"
        if "OFFERING" in combined or "3.02" in items:
            return "RIGHTS_ISSUE"
        return None

    def _determine_time_context(self, accept_str: str) -> str:
        # e.g., 2026-10-31T16:30:00.000Z
        try:
            if "T" in accept_str:
                time_part = accept_str.split("T")[1][:5]
                hh, mm = map(int, time_part.split(":"))
                # Post 16:00 ET is after-hours
                if hh >= 16 or (hh == 16 and mm > 0):
                    return "AFTERHOURS"
                if hh < 9 or (hh == 9 and mm < 30):
                    return "PREMARKET"
                return "INTRADAY"
        except Exception:
            pass
        return "DATE_ONLY"

    def _extract_date(self, text: str, default_date: date) -> date:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        return default_date

    def collect(self, since: datetime) -> list[RawEvent]:
        """Collect recent SEC corporate events."""
        start_time = time.time()
        events: list[RawEvent] = []

        try:
            if self.fixture_path and self.fixture_path.exists():
                with open(self.fixture_path, mode="r", encoding="utf-8") as f:
                    data = json.load(f)
                payloads = [data]
            else:
                # Live SEC submissions API could query target watchlist CIKs
                # In default unconfigured environment, return empty gracefully
                payloads = []

            for data in payloads:
                cik = str(data.get("cik", "")).zfill(10)
                company_name = data.get("name", "Unknown Corp")
                tickers = data.get("tickers", [])
                primary_ticker = tickers[0] if tickers else ""
                if not primary_ticker:
                    continue

                recent = data.get("filings", {}).get("recent", {})
                accession_numbers = recent.get("accessionNumber", [])
                filing_dates = recent.get("filingDate", [])
                acceptance_datetimes = recent.get("acceptanceDateTime", [])
                forms = recent.get("form", [])
                items_list = recent.get("items", [])
                descriptions = recent.get("primaryDocDescription", [])
                event_dates = recent.get("event_date", [])
                primary_docs = recent.get("primaryDocument", [])

                for i, acc_num in enumerate(accession_numbers):
                    form = forms[i] if i < len(forms) else ""
                    items_str = items_list[i] if i < len(items_list) else ""
                    desc = descriptions[i] if i < len(descriptions) else ""

                    ev_type = self._determine_event_type(form, items_str, desc)
                    if not ev_type:
                        continue

                    f_date_str = filing_dates[i] if i < len(filing_dates) else ""
                    try:
                        ann_date = datetime.fromisoformat(f_date_str) if f_date_str else since
                    except ValueError:
                        ann_date = since

                    accept_str = acceptance_datetimes[i] if i < len(acceptance_datetimes) else ""
                    time_ctx = self._determine_time_context(accept_str)

                    # Extract event_date
                    if i < len(event_dates) and event_dates[i]:
                        ev_date = date.fromisoformat(str(event_dates[i])[:10])
                    else:
                        ev_date = self._extract_date(desc, default_date=ann_date.date())

                    clean_acc = acc_num.replace("-", "")
                    doc_name = primary_docs[i] if i < len(primary_docs) else ""
                    doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{clean_acc}/{doc_name}" if cik and doc_name else ""

                    events.append(
                        RawEvent(
                            source_name="SEC",
                            source_kind="REGULATOR",
                            source_event_uid=acc_num,
                            source_url=doc_url,
                            country="US",
                            primary_ticker=primary_ticker,
                            primary_company=company_name,
                            event_type=ev_type,
                            event_name=f"{company_name} {desc or form}".strip(),
                            announced_at=ann_date,
                            event_date=ev_date,
                            event_time_context=time_ctx,  # type: ignore
                            status="CONFIRMED",
                            evidence_text=f"{form} {items_str}: {desc}".strip(),
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
