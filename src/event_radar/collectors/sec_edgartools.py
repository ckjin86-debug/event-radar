"""PILOT — edgartools-based variant of the SEC 8-K collector.

This module mirrors :class:`event_radar.collectors.sec.SecCollector` (same
event types, same classification helpers, same ``RawEvent`` output schema)
but gets its filing data from the ``edgartools`` library instead of
hand-rolled EDGAR parsing.

Why: the production collector's discovery depends on literal text matching
of the EDGAR daily master index header. EDGAR's real header ends with
"File Name" (with a space); the original code waited for "Filename", never
matched, and silently parsed zero rows from every live index — the failure
was invisible until someone noticed the SEC source had gone quiet.
edgartools reaches the same EDGAR data through the structured submissions
JSON (per company) and parses the daily *form* index positionally
(pyarrow ``read_csv`` with ``skip_rows`` + named columns), so no literal
header-string gate exists in either path. It is also a maintained library
with its own test suite, so an EDGAR format drift is more likely to be
caught (and fixed) upstream than in a local regex.

Pilot scope / caveats:
- Not wired into the collector registry or the pipeline; nothing in
  production uses this yet.
- ``edgartools`` is an optional dependency for this pilot only (not in
  ``pyproject.toml`` dependencies).
- Discovery differs by design: production scans the daily master index
  for *all* filers and then filters to the large-cap universe, while this
  pilot walks an explicit ticker list (per-company submissions). That is
  the right shape for a parsing-parity pilot; universe-scale discovery
  via ``edgar.get_filings(filing_date=...)`` (daily form index) is exposed
  as :meth:`discover_day` for comparison but not used by ``collect``.
- Event-field semantics intentionally duplicate ``SecCollector`` — the
  classification helpers are literally reused — so any output difference
  in the pilot comparison is attributable to the data/parsing layer, not
  to re-implemented business rules.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Optional

try:
    import edgar as _edgar
except ImportError:  # pragma: no cover - exercised only without the optional dep
    _edgar = None

from event_radar.collectors.base import CollectorRunLog, log_collector_run
from event_radar.collectors.sec import SEC_DEFAULT_USER_AGENT, TARGET_FORMS, SecCollector
from event_radar.models import RawEvent


class SecEdgartoolsCollector:
    """SEC 8-K collector backed by edgartools (pilot, not for production wiring)."""

    source_name: str = "SEC"

    def __init__(
        self,
        user_agent: str = SEC_DEFAULT_USER_AGENT,
        tickers: Optional[list[str]] = None,
    ):
        self.user_agent = user_agent
        self.tickers = [t.strip().upper() for t in tickers or [] if t and t.strip()]
        # Reuse the production classification helpers verbatim so event
        # typing / time-context / date extraction cannot drift between the
        # two implementations during comparison.
        self._classifier = SecCollector(request_interval=0)

    # ------------------------------------------------------------------
    @staticmethod
    def _require_edgar():
        if _edgar is None:
            raise RuntimeError(
                "edgartools is not installed; this pilot collector needs the "
                "optional 'edgartools' package (pilot venv only)."
            )

    def _identity(self) -> None:
        self._require_edgar()
        _edgar.set_identity(self.user_agent)

    # ------------------------------------------------------------------
    # Row -> RawEvent (one edgartools filings-table row = one submissions
    # "recent" entry; the table carries the same fields as the JSON arrays
    # the production collector zips together by hand.)
    # ------------------------------------------------------------------
    def _row_to_event(
        self,
        row: dict,
        *,
        cik: str,
        company_name: str,
        primary_ticker: str,
        since: datetime,
    ) -> Optional[RawEvent]:
        form = str(row.get("form") or "").upper()
        if form not in TARGET_FORMS:
            return None

        items_str = str(row.get("items") or "")
        desc = str(row.get("primaryDocDescription") or "")

        ev_type = self._classifier._determine_event_type(form, items_str, desc)
        if not ev_type:
            return None

        filing_date = row.get("filing_date")
        if isinstance(filing_date, datetime):
            ann_date = filing_date
        elif isinstance(filing_date, date):
            ann_date = datetime(filing_date.year, filing_date.month, filing_date.day)
        elif filing_date:
            try:
                ann_date = datetime.fromisoformat(str(filing_date)[:10])
            except ValueError:
                ann_date = since
        else:
            ann_date = since
        if ann_date < since:
            return None

        # edgartools returns acceptanceDateTime as a tz-aware datetime,
        # while the production helper expects the raw EDGAR string form
        # ("2026-11-02T21:30:23..."). isoformat() restores the "T" shape.
        accept_raw = row.get("acceptanceDateTime")
        if isinstance(accept_raw, datetime):
            accept_str = accept_raw.isoformat()
        else:
            accept_str = str(accept_raw or "")
        time_ctx = self._classifier._determine_time_context(accept_str)
        ev_date = self._classifier._extract_date(desc, default_date=ann_date.date())

        accession = str(row.get("accession_number") or "")
        if not accession:
            return None
        clean_acc = accession.replace("-", "")
        doc_name = str(row.get("primaryDocument") or "")
        cik_padded = str(cik).zfill(10)
        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik_padded)}/{clean_acc}/{doc_name}"
            if doc_name
            else ""
        )

        return RawEvent(
            source_name="SEC",
            source_kind="REGULATOR",
            source_event_uid=accession,
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

    # ------------------------------------------------------------------
    def events_for_ticker(self, ticker: str, since: datetime) -> list[RawEvent]:
        """Collect one company's classifiable 8-K events via edgartools."""
        self._identity()
        company = _edgar.Company(ticker)
        primary_ticker = (company.tickers[0] if company.tickers else ticker).upper()
        date_range = f"{since.date().isoformat()}:{datetime.now().date().isoformat()}"
        filings = company.get_filings(form=sorted(TARGET_FORMS), filing_date=date_range)
        if filings is None or len(filings) == 0:
            return []

        events: list[RawEvent] = []
        for row in filings.data.to_pylist():
            event = self._row_to_event(
                row,
                cik=str(company.cik),
                company_name=company.name,
                primary_ticker=primary_ticker,
                since=since,
            )
            if event is not None:
                events.append(event)
        return events

    def discover_day(self, day: date) -> list[dict]:
        """Return raw edgartools rows for one day's 8-K filings (all filers).

        Uses edgartools' daily form-index path — the discovery analogue of
        the production collector's master-index scan — for parity checks.
        """
        self._identity()
        filings = _edgar.get_filings(
            filing_date=day.isoformat(), form=sorted(TARGET_FORMS)
        )
        if filings is None or len(filings) == 0:
            return []
        return filings.data.to_pylist()

    # ------------------------------------------------------------------
    def collect(self, since: datetime) -> list[RawEvent]:
        """Collect events for the explicitly configured ticker list."""
        start_time = time.time()
        events: list[RawEvent] = []
        try:
            self._require_edgar()
            for ticker in self.tickers:
                events.extend(self.events_for_ticker(ticker, since))

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

        except Exception as exc:
            duration = time.time() - start_time
            log_collector_run(
                CollectorRunLog(
                    source_name=self.source_name,
                    status="FAILED",
                    items_count=0,
                    duration_sec=duration,
                    error_message=str(exc),
                )
            )
            return []
