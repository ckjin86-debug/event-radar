"""SEC EDGAR Schedule 13D/13G 5% ownership filing collector (US).

The US counterpart of DartFivePctCollector: the original "DART & SEC 5%
Super Radar" treated Korean 대량보유상황보고서 and US Schedule 13D/13G as
one signal family scored by the same 7-strategy engine
(event_radar.five_pct_rules). This collector reproduces the original's
SEC pipeline (background.js `fetchSecEdgarPipeline` /
`parseSecPrimaryDocXml`):

1. Discovery: the EDGAR full-text search index
   (efts.sec.gov/LATEST/search-index) for SCHEDULE 13D/13G and SC 13D/13G,
   including /A amendments, over the requested date range. Subject
   company and filer come from the hit's display_names (in that order),
   the ticker from the subject's "(TICKER)" suffix.
2. Verification: each filing's official primary_doc.xml is parsed for
   percentOfClass, aggregateAmountOwned, reportingPersonName and the
   Item 3 fundsSource. A filing whose percentOfClass cannot be read is
   skipped — the original never substituted a placeholder value, and
   neither do we (in particular there is no sample-data fallback here).
3. Scoring: the extracted item is scored by the same
   five_pct_rules.evaluate_signal_score used for KR filings, and the
   analysis rides on the event in raw_payload["five_pct_analysis"] with
   the same structure as the KR collector's payload.

Fields the XML does not yield are left empty and recorded in
analysis["missing_fields"] instead of being estimated.
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from event_radar.collectors.base import CollectorRunLog, log_collector_run
from event_radar.collectors.dart_five_pct import DartFivePctCollector
from event_radar.collectors.sec import SEC_COMPANY_TICKERS_URL, SEC_DEFAULT_USER_AGENT
from event_radar.five_pct_rules import compute_ownership_freshness, evaluate_signal_score
from event_radar.models import RawEvent


SEC_EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_PRIMARY_DOC_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/primary_doc.xml"
)
SEC_FILING_INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/{accession}-index.html"
)
SEC_13DG_FORMS = (
    "SCHEDULE 13D,SCHEDULE 13D/A,SC 13D,SC 13D/A,"
    "SCHEDULE 13G,SCHEDULE 13G/A,SC 13G,SC 13G/A"
)
# The original extension scanned at most 20 filings per run.
MAX_FILINGS = 20

_TICKER_RE = re.compile(r"\(([A-Z]{1,5})\)")
_CIK_SUFFIX_RE = re.compile(r"\s*\(CIK[^)]+\)", re.IGNORECASE)
_MONEY_RE = re.compile(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?)")


class SecFivePctCollector:
    """Collector for US 5% ownership filings (Schedule 13D/13G) from SEC EDGAR."""

    source_name: str = "SEC_13DG"

    def __init__(
        self,
        fixture_path: Optional[Path | str] = None,
        user_agent: str = SEC_DEFAULT_USER_AGENT,
        timeout: int = 10,
        request_interval: float = 0.12,
    ):
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.timeout = timeout
        self.request_interval = max(0.0, request_interval)
        self._last_request_at = 0.0
        self._ticker_map_cache: Optional[dict[str, tuple[str, str]]] = None

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )

    # ------------------------------------------------------------------
    # HTTP (SEC fair-access rate limiting, same pattern as SecCollector)
    # ------------------------------------------------------------------
    def _get(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None):
        if self.request_interval > 0 and self._last_request_at:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self.request_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        response = self.session.get(
            url, params=params, headers=headers, timeout=self.timeout
        )
        self._last_request_at = time.monotonic()
        return response

    # ------------------------------------------------------------------
    # Fixture loading: {"efts": {...search-index payload...},
    #                   "primary_docs": {adsh: xml_text},
    #                   "company_tickers": {...company_tickers.json payload...}}
    # ------------------------------------------------------------------
    def _load_fixture(self) -> Optional[dict]:
        if self.fixture_path and self.fixture_path.exists():
            with open(self.fixture_path, mode="r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        return None

    # ------------------------------------------------------------------
    # CIK -> (ticker, company) mapping (SEC company_tickers.json)
    # ------------------------------------------------------------------
    @staticmethod
    def _ticker_map_from_payload(payload: object) -> dict[str, tuple[str, str]]:
        mapping: dict[str, tuple[str, str]] = {}
        if isinstance(payload, dict):
            records = payload.values()
        elif isinstance(payload, list):
            records = payload
        else:
            return mapping
        for record in records:
            if not isinstance(record, dict):
                continue
            cik = str(record.get("cik_str", "")).strip()
            ticker = str(record.get("ticker", "")).strip().upper()
            title = str(record.get("title", "")).strip()
            if not cik or not ticker:
                continue
            mapping.setdefault(cik.zfill(10), (ticker, title))
        return mapping

    def _load_company_tickers(
        self, fixture: Optional[dict]
    ) -> dict[str, tuple[str, str]]:
        """Load the CIK -> (ticker, company) map once per run; failure degrades to {}."""
        if self._ticker_map_cache is not None:
            return self._ticker_map_cache

        mapping: dict[str, tuple[str, str]] = {}
        if fixture is not None:
            mapping = self._ticker_map_from_payload(fixture.get("company_tickers"))
        else:
            try:
                response = self._get(SEC_COMPANY_TICKERS_URL)
                if response.status_code == 200:
                    mapping = self._ticker_map_from_payload(response.json())
            except Exception:
                # The display names usually carry the ticker already; the
                # map is only a fallback, exactly as in SecCollector.
                mapping = {}

        self._ticker_map_cache = mapping
        return mapping

    # ------------------------------------------------------------------
    # Stage 1: EDGAR full-text search discovery (original parameters)
    # ------------------------------------------------------------------
    def _discover_hits(
        self, since: datetime, fixture: Optional[dict]
    ) -> list[dict]:
        if fixture is not None:
            payload = fixture.get("efts")
            hits = ((payload or {}).get("hits") or {}).get("hits") or []
            return [hit for hit in hits if isinstance(hit, dict)]

        params = {
            "forms": SEC_13DG_FORMS,
            "dateRange": "custom",
            "startdt": since.date().isoformat(),
            "enddt": datetime.now().date().isoformat(),
        }
        resp = self._get(
            SEC_EFTS_SEARCH_URL,
            params=params,
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise ConnectionError(f"SEC EDGAR search HTTP {resp.status_code}")
        payload = resp.json()
        hits = ((payload or {}).get("hits") or {}).get("hits") or []
        return [hit for hit in hits if isinstance(hit, dict)]

    # ------------------------------------------------------------------
    # Stage 2: primary_doc.xml parsing (original parseSecPrimaryDocXml)
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_tag(xml: str, tag: str) -> Optional[str]:
        match = re.search(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", xml, re.IGNORECASE)
        if not match:
            return None
        return re.sub(r"<[^>]+>", "", match.group(1)).strip()

    def _load_primary_doc_xml(
        self, cik: str, adsh: str, fixture: Optional[dict]
    ) -> Optional[str]:
        if fixture is not None:
            docs = fixture.get("primary_docs")
            if isinstance(docs, dict):
                text = docs.get(adsh)
                return text if isinstance(text, str) else None
            return None

        try:
            cik_num = str(int(str(cik).replace(",", "").strip() or "0"))
        except (TypeError, ValueError):
            return None
        if cik_num == "0":
            return None
        try:
            resp = self._get(
                SEC_PRIMARY_DOC_URL.format(cik=cik_num, adsh=adsh.replace("-", ""))
            )
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        return resp.text

    def _parse_primary_doc(self, xml: Optional[str]) -> Optional[dict]:
        """Extract the ownership facts from a 13D/13G primary_doc.xml.

        Returns None when percentOfClass is unreadable — the original
        dropped such filings rather than guessing a stake.
        """
        if not xml:
            return None

        pct_raw = self._extract_tag(xml, "percentOfClass")
        percent = None
        if pct_raw is not None:
            try:
                parsed = float(pct_raw)
            except (TypeError, ValueError):
                parsed = math.nan
            if not math.isnan(parsed):
                percent = round(parsed, 2)
        if percent is None:
            return None

        shares_raw = self._extract_tag(xml, "aggregateAmountOwned")
        numeric_shares = 0
        aggregate = "-"
        if shares_raw:
            try:
                numeric_shares = int(round(float(shares_raw.replace(",", ""))))
            except (TypeError, ValueError):
                numeric_shares = 0
            if numeric_shares > 0:
                aggregate = f"{numeric_shares:,}"

        # Priority 2 (DERIVED): Item 3 fundsSource total amount / shares.
        funds_source = self._extract_tag(xml, "fundsSource")
        est_avg_price = None
        price_source = None
        if funds_source and numeric_shares > 0:
            money = _MONEY_RE.search(funds_source)
            if money:
                try:
                    raw_dollar = float(money.group(1).replace(",", ""))
                except (TypeError, ValueError):
                    raw_dollar = 0.0
                if raw_dollar > 1000:
                    derived = raw_dollar / numeric_shares
                    if 0.5 <= derived <= 5000:
                        est_avg_price = round(derived, 2)
                        price_source = (
                            f"DERIVED: SEC 13D Item 3 총취득금액(${money.group(1)})"
                            f"/취득주식수({numeric_shares:,}주)"
                        )

        purpose_text = self._extract_tag(xml, "transactionPurpose")
        tx_desc = self._extract_tag(xml, "transactionDesc")
        snippet_source = purpose_text or tx_desc or funds_source or ""
        snippet = re.sub(r"\s+", " ", snippet_source)[:140]

        return {
            "percent_of_class": percent,
            "aggregate_amount_owned": aggregate,
            "numeric_shares": numeric_shares,
            "reporting_person_name": self._extract_tag(xml, "reportingPersonName"),
            "funds_source": funds_source,
            "est_avg_price": est_avg_price,
            "price_source": price_source,
            "summary_snippet": snippet,
        }

    # ------------------------------------------------------------------
    # Name helpers (original display_names handling)
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_display_name(raw: str) -> str:
        return _CIK_SUFFIX_RE.sub("", str(raw or "")).strip()

    # ------------------------------------------------------------------
    def _event_from_hit(
        self,
        hit: dict,
        fixture: Optional[dict],
        ticker_map: dict[str, tuple[str, str]],
        since: datetime,
    ) -> Optional[RawEvent]:
        src = hit.get("_source") or {}
        form = str(src.get("form") or src.get("root_form") or "SCHEDULE 13D").strip()
        display_names = src.get("display_names") or []
        if not isinstance(display_names, list) or not display_names:
            return None
        subject_raw = str(display_names[0] or "")
        filer_raw = str(
            display_names[1] if len(display_names) > 1 else display_names[0] or ""
        )
        if not subject_raw:
            return None

        adsh = str(src.get("adsh") or "").strip()
        if not adsh:
            adsh = str(hit.get("_id") or "").split(":")[0].strip()
        ciks = src.get("ciks") or []
        cik = str(ciks[0]).strip() if isinstance(ciks, list) and ciks else ""
        if not adsh or not cik:
            return None

        file_date = str(src.get("file_date") or since.date().isoformat())[:10]
        is_13d = "13D" in form
        is_amend = "/A" in form

        # Ticker: the subject's "(TICKER)" suffix first (original), then
        # the SEC company_tickers mapping for the subject CIK.
        ticker_match = _TICKER_RE.search(subject_raw)
        ticker = ticker_match.group(1) if ticker_match else ""
        mapped_ticker, mapped_title = ticker_map.get(cik.zfill(10), ("", ""))
        missing_fields: list[str] = []
        if not ticker:
            ticker = mapped_ticker
        if not ticker:
            missing_fields.append("ticker")

        corp_name = self._clean_display_name(subject_raw)
        if ticker and f"({ticker})" in corp_name:
            corp_name = re.sub(r"\s+", " ", corp_name.replace(f"({ticker})", "")).strip()
        if mapped_title:
            corp_name = mapped_title
        filer_name = self._clean_display_name(filer_raw)

        detail = self._parse_primary_doc(
            self._load_primary_doc_xml(cik, adsh, fixture)
        )
        if detail is None:
            # percentOfClass unreadable: the original skipped the filing.
            return None

        hold_rt = detail["percent_of_class"]
        reporter = detail["reporting_person_name"] or filer_name
        if not detail["reporting_person_name"]:
            missing_fields.append("reportingPersonName")
        if detail["numeric_shares"] <= 0:
            missing_fields.append("aggregateAmountOwned")
        if detail["est_avg_price"] is None:
            missing_fields.append("fundsSource")

        curr_purpose = "경영권 영향" if is_13d else "단순투자"
        if is_13d:
            prev_purpose = "경영권 영향" if is_amend else "단순투자"
        else:
            prev_purpose = "단순투자"
        stk_rt_var = 0 if is_amend else hold_rt
        hold_cnt = detail["aggregate_amount_owned"]
        is_new_entry = (not is_amend) and hold_rt >= 5.0

        report_nm = (
            f"{form} ({'Active Ownership' if is_13d else 'Passive Ownership'})"
        )
        report_resn = (
            f"SCHEDULE {'13D' if is_13d else '13G'} ({adsh}): "
            f"{detail['summary_snippet'] or 'Official SEC Ownership Filing'}"
        )

        item = {
            "market": "US",
            "rcept_no": adsh,
            "rcept_dt": file_date,
            "prev_rcept_dt": None,
            "first_entry_dt": file_date,
            "corp_code": cik,
            "corp_name": corp_name,
            "stock_code": ticker,
            "rpror_nm": reporter,
            "hold_stock_cnt": hold_cnt,
            "stk_cnt_var": "-",
            "hold_stock_rt": hold_rt,
            "stk_rt_var": stk_rt_var,
            "curr_purpose": curr_purpose,
            "prev_purpose": prev_purpose,
            "report_resn": report_resn,
            "report_nm": report_nm,
            "is_new_entry": is_new_entry,
            "accum_count": 1 if is_new_entry else 0,
            "est_avg_price": detail["est_avg_price"],
            "price_source": detail["price_source"],
            "current_price": None,
            "ownership_freshness": compute_ownership_freshness(file_date),
        }
        evaluation = evaluate_signal_score(item)

        history_entry = {
            "rcept_dt": file_date,
            "rcept_no": adsh,
            "hold_stock_rt": hold_rt,
            "stk_rt_var": stk_rt_var,
            "hold_stock_cnt": hold_cnt,
            "stk_cnt_var": "-",
            "curr_purpose": curr_purpose,
            "report_resn": report_resn,
        }
        processed = {**item, "eval": evaluation, "history": [history_entry]}
        analysis = DartFivePctCollector._analysis_payload(processed)
        if missing_fields:
            analysis["missing_fields"] = missing_fields

        try:
            ann_date = datetime.strptime(file_date, "%Y-%m-%d")
        except ValueError:
            ann_date = since

        facts = [report_nm]
        if reporter:
            facts.append(f"대표보고자 {reporter}")
        if hold_rt:
            facts.append(f"보유비율 {hold_rt}%")
        if isinstance(stk_rt_var, (int, float)) and stk_rt_var:
            facts.append(f"보유비율 증감 {stk_rt_var}%p")
        if hold_cnt and hold_cnt != "-":
            facts.append(f"보유주식수 {hold_cnt}주")
        evidence_text = " · ".join(facts)

        event_name = f"{corp_name} {report_nm}".strip()
        if reporter:
            event_name = f"{event_name} (대표보고자: {reporter})"

        try:
            cik_int = str(int(cik))
            source_url = SEC_FILING_INDEX_URL.format(
                cik=cik_int, adsh=adsh.replace("-", ""), accession=adsh
            )
        except (TypeError, ValueError):
            source_url = ""

        if ticker:
            primary_ticker = ticker
        elif cik.isdigit():
            primary_ticker = f"CIK{int(cik)}"
        else:
            primary_ticker = cik

        raw_payload = {
            "sec_filing": {
                key: value
                for key, value in processed.items()
                if key not in {"eval", "history"}
            },
            "history": [history_entry],
            "five_pct_analysis": analysis,
        }

        return RawEvent(
            source_name="SEC_13DG",
            source_kind="REGULATOR",
            source_event_uid=adsh,
            source_url=source_url,
            country="US",
            primary_ticker=primary_ticker,
            primary_company=corp_name,
            event_type="5PCT_OWNERSHIP",
            event_name=event_name,
            announced_at=ann_date,
            event_date=ann_date.date(),
            event_time_context="DATE_ONLY",
            status="CONFIRMED",
            evidence_text=evidence_text,
            ingest_mode="AUTO",
            raw_payload=raw_payload,
        )

    # ------------------------------------------------------------------
    def collect(self, since: datetime) -> list[RawEvent]:
        """Collect recent Schedule 13D/13G filings received since `since`."""
        start_time = time.time()
        events: list[RawEvent] = []

        try:
            fixture = self._load_fixture()
            hits = self._discover_hits(since, fixture)
            ticker_map = self._load_company_tickers(fixture)

            for hit in hits[:MAX_FILINGS]:
                event = self._event_from_hit(hit, fixture, ticker_map, since)
                if event is not None:
                    events.append(event)

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
