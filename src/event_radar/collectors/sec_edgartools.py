"""SEC EDGAR 8-K collector backed by edgartools (production).

This is the production implementation of the SEC source. It mirrors the
legacy hand-rolled collector (:class:`event_radar.collectors.sec.SecCollector`,
kept for fallback / comparison) — same event types, same classification
helpers, same ``RawEvent`` output schema — but reaches EDGAR data through
the maintained ``edgartools`` library instead of local text parsing.

Why (adopted 2026-11-07 after the pilot on branch ``pilot/edgartools-sec``):

- The legacy discovery gate was a literal, case-sensitive header-prefix
  match on the daily master index. Plausible EDGAR header drifts
  (lowercase, spacing, BOM, column order) still make it return *zero
  rows with no error* — the failure mode behind the historical SEC
  outage, where the source silently went quiet. edgartools parses the
  index positionally and either returns the rows or raises (loud).
- The legacy event conversion zipped the submissions JSON's parallel
  arrays by hand. edgartools' filings table carries the same fields as
  typed rows.

Discovery shape (pilot recommendation "b"): scan each day's EDGAR *form
index* via edgartools for 8-K / 8-K/A filings, apply the large-cap
universe filter (the very same ``SecCollector._large_cap_ciks`` logic),
then convert only the discovered filings, using each company's edgartools
filings table for the detail fields (items, acceptanceDateTime, primary
document) the bare index rows do not carry.

Semantics pinned by the pilot:

- ``acceptanceDateTime`` comes back from edgartools as a tz-aware
  datetime; it is normalised with ``isoformat()`` before the legacy
  time-context helper sees it (the helper expects the raw "…T…" string).
- Event classification helpers are literally reused from ``SecCollector``
  so typing / time-context / date extraction cannot drift between the
  two implementations.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    import edgar as _edgar
except ImportError:  # pragma: no cover - exercised only without the dependency
    _edgar = None

from event_radar.collectors.base import CollectorRunLog, log_collector_run
from event_radar.collectors.sec import SEC_DEFAULT_USER_AGENT, TARGET_FORMS, SecCollector
from event_radar.models import RawEvent


class SecEdgartoolsCollector:
    """SEC 8-K collector backed by edgartools."""

    source_name: str = "SEC"

    def __init__(
        self,
        user_agent: str = SEC_DEFAULT_USER_AGENT,
        tickers: Optional[list[str]] = None,
        universe_path: Optional[Path | str] = None,
        universe_tickers: Optional[set[str]] = None,
    ):
        self.user_agent = user_agent
        self.tickers = [t.strip().upper() for t in tickers or [] if t and t.strip()]
        # No fixture mode: kept as an attribute so wiring/tests can rely
        # on the same shape as the legacy collector.
        self.fixture_path = None
        # Reuse the production classification helpers — and, for
        # discovery, the production ticker map / universe / window logic —
        # verbatim, so behaviour cannot drift between implementations.
        self._classifier = SecCollector(
            request_interval=0,
            universe_path=universe_path,
            universe_tickers=universe_tickers,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _require_edgar():
        if _edgar is None:
            raise RuntimeError(
                "edgartools is not installed; the SEC collector needs the "
                "'edgartools' package (see pyproject.toml)."
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
        the legacy collector's master-index scan.
        """
        self._identity()
        filings = _edgar.get_filings(
            filing_date=day.isoformat(), form=sorted(TARGET_FORMS)
        )
        if filings is None or len(filings) == 0:
            return []
        return filings.data.to_pylist()

    # ------------------------------------------------------------------
    # Production discovery: daily form index -> large-cap filter ->
    # per-company conversion of the discovered filings only.
    # ------------------------------------------------------------------
    def _discover_candidates(self, since: datetime) -> dict[str, dict]:
        """Map CIK -> {accessions, ticker, company} for discovered 8-Ks."""
        try:
            ticker_map = self._classifier._load_company_tickers()
        except Exception:
            # The per-company filings table also carries tickers, so a
            # mapping failure is non-fatal (same stance as the legacy
            # collector).
            ticker_map = {}

        # Large-cap filter first, so detail fetches are never spent on
        # filings that would be discarded anyway.
        large_cap_ciks = self._classifier._large_cap_ciks(ticker_map)

        candidates: dict[str, dict] = {}
        seen_accessions: set[str] = set()
        for day in self._classifier._discovery_dates(since):
            try:
                rows = self.discover_day(day)
            except Exception:
                # One day's index being unavailable (weekend / not yet
                # published) must not sink the whole run.
                continue
            for row in rows:
                cik = str(row.get("cik") or "").zfill(10)
                if not cik.strip("0"):
                    continue
                if large_cap_ciks is not None and cik not in large_cap_ciks:
                    continue
                accession = str(row.get("accession_number") or "")
                if not accession or accession in seen_accessions:
                    continue
                seen_accessions.add(accession)
                ticker, mapped_company = ticker_map.get(cik, ("", ""))
                entry = candidates.setdefault(
                    cik,
                    {
                        "accessions": set(),
                        "ticker": ticker,
                        "company": mapped_company or str(row.get("company") or ""),
                    },
                )
                entry["accessions"].add(accession)
        return candidates

    def _events_for_cik(
        self,
        cik: str,
        candidate: dict,
        since: datetime,
    ) -> list[RawEvent]:
        """Convert one company's discovered filings via its filings table."""
        try:
            company = _edgar.Company(int(cik))
        except Exception:
            return []
        date_range = (
            f"{since.date().isoformat()}:{datetime.now().date().isoformat()}"
        )
        try:
            filings = company.get_filings(
                form=sorted(TARGET_FORMS), filing_date=date_range
            )
        except Exception:
            return []
        if filings is None or len(filings) == 0:
            return []

        primary_ticker = (
            candidate.get("ticker")
            or (company.tickers[0] if company.tickers else "")
        ).upper()
        if not primary_ticker:
            return []
        company_name = candidate.get("company") or company.name

        events: list[RawEvent] = []
        for row in filings.data.to_pylist():
            if str(row.get("accession_number") or "") not in candidate["accessions"]:
                continue
            event = self._row_to_event(
                row,
                cik=cik,
                company_name=company_name,
                primary_ticker=primary_ticker,
                since=since,
            )
            if event is not None:
                events.append(event)
        return events

    # ------------------------------------------------------------------
    def collect(self, since: datetime) -> list[RawEvent]:
        """Collect recent large-cap SEC 8-K events via edgartools."""
        start_time = time.time()
        events: list[RawEvent] = []
        try:
            self._require_edgar()
            if self.tickers:
                # Explicit watchlist mode (parity checks / tests).
                for ticker in self.tickers:
                    events.extend(self.events_for_ticker(ticker, since))
            else:
                candidates = self._discover_candidates(since)
                for cik, candidate in candidates.items():
                    events.extend(self._events_for_cik(cik, candidate, since))

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
