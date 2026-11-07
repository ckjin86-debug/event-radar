"""DART 5% large-shareholding (주식등의 대량보유상황보고서) disclosure collector.

Separate from DartCollector on purpose: the regular collector queries
pblntf_ty=B (주요사항보고서) for corporate actions, while large-shareholding
reports live under pblntf_ty=D (지분공시). The two feeds have different
semantics — a 5% filing is an already-received disclosure, not a scheduled
event — so they are collected and exported separately (see export.py, which
routes these rows to five_pct.json instead of events.json).

Collection follows the original "DART 5% Super Radar" 2-stage pipeline:

1. Discovery: list.json with pblntf_ty=D and pblntf_detail_ty=D001
   (주식등의대량보유상황보고서) finds newly received filings.
2. History: for each discovered corp_code, majorstock.json returns the
   reporter's full official filing history. The history is processed by
   event_radar.five_pct_rules (amendment de-duplication, genuine
   accumulation streaks, S1~S7 signal scoring) and the latest filing per
   (corp, reporter) becomes one event carrying the analysis in
   raw_payload["five_pct_analysis"].

When majorstock.json returns no rows for a corp, the collector degrades
to the previous behaviour: one event per list row, enriched best-effort
from elestock.json.
"""

from __future__ import annotations
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import requests
from event_radar.models import RawEvent
from event_radar.collectors.base import CollectorRunLog, log_collector_run
from event_radar.five_pct_rules import process_majorstock_history


DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_MAJORSTOCK_URL = "https://opendart.fss.or.kr/api/majorstock.json"
DART_ELESTOCK_URL = "https://opendart.fss.or.kr/api/elestock.json"
DART_DISCLOSURE_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

PAGE_COUNT = 100
MAX_PAGES = 5
# Per-run cap on majorstock history lookups (the original used 30; the
# radar's wider discovery window needs headroom, capped at 60 corps).
MAX_MAJORSTOCK_CORPS = 60


class DartFivePctCollector:
    """Collector for Korean 5% large-shareholding filings from OpenDART."""

    source_name: str = "DART_5PCT"

    def __init__(
        self,
        api_key=None,
        fixture_path: Optional[Path | str] = None,
        timeout: int = 10,
    ):
        self.api_key = api_key or os.getenv("DART_API_KEY", "")
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EventRadar/1.0"
        })

    # ------------------------------------------------------------------
    # Fixture loading: {"list": [...], "majorstock": {corp_code: payload},
    #                   "elestock": {corp_code: payload}}
    # ------------------------------------------------------------------
    def _load_fixture(self) -> Optional[dict]:
        if self.fixture_path and self.fixture_path.exists():
            with open(self.fixture_path, mode="r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        return None

    # (fixture mode is active only when a fixture file actually loaded)

    @staticmethod
    def _fixture_map(fixture: Optional[dict], key: str) -> dict:
        if not fixture:
            return {}
        value = fixture.get(key, {})
        return value if isinstance(value, dict) else {}

    # ------------------------------------------------------------------
    # Stage 1: list.json discovery (pblntf_ty=D, pblntf_detail_ty=D001)
    # ------------------------------------------------------------------
    def _load_list_items(
        self, since: datetime, fixture: Optional[dict]
    ) -> list[dict]:
        if fixture is not None:
            rows = fixture.get("list", [])
            return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

        if not self.api_key:
            return []

        now = datetime.now()
        items: list[dict] = []
        total_page = 1
        page_no = 1
        while page_no <= min(total_page, MAX_PAGES):
            params = {
                "crtfc_key": self.api_key,
                "bgn_de": since.strftime("%Y%m%d"),
                "end_de": now.strftime("%Y%m%d"),
                "pblntf_ty": "D",
                "pblntf_detail_ty": "D001",
                "page_no": page_no,
                "page_count": PAGE_COUNT,
            }
            resp = self.session.get(DART_LIST_URL, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                raise ConnectionError(f"DART HTTP {resp.status_code}")
            payload = resp.json()
            status = str(payload.get("status", "000"))
            if status == "013":
                # No data for the range: a valid, empty result.
                break
            if status != "000":
                raise ConnectionError(f"DART list API status {status}: {payload.get('message', '')}")
            items.extend(payload.get("list", []))
            try:
                total_page = int(payload.get("total_page") or 1)
            except (TypeError, ValueError):
                total_page = 1
            page_no += 1
        return items

    # ------------------------------------------------------------------
    # Stage 2: majorstock.json official history per corp (cached per run)
    # ------------------------------------------------------------------
    def _majorstock_rows_for_corp(
        self,
        corp_code: str,
        fixture: Optional[dict],
        cache: dict[str, list[dict]],
    ) -> list[dict]:
        if corp_code in cache:
            return cache[corp_code]

        rows: list[dict] = []
        if fixture is not None:
            payload = self._fixture_map(fixture, "majorstock").get(corp_code)
            rows = self._normalize_history_payload(payload)
        elif self.api_key and corp_code:
            try:
                resp = self.session.get(
                    DART_MAJORSTOCK_URL,
                    params={"crtfc_key": self.api_key, "corp_code": corp_code},
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    if str(payload.get("status", "")) == "000":
                        rows = self._normalize_history_payload(payload)
            except Exception:
                # History is the primary path, but a failed lookup degrades
                # to the elestock path instead of dropping the filing.
                rows = []

        cache[corp_code] = rows
        return rows

    @staticmethod
    def _normalize_history_payload(payload: object) -> list[dict]:
        if isinstance(payload, dict):
            rows = payload.get("list", [])
            return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []

    # ------------------------------------------------------------------
    # Degraded path: elestock.json enrichment (best effort)
    # ------------------------------------------------------------------
    def _elestock_rows_for_corp(
        self,
        corp_code: str,
        fixture: Optional[dict],
        cache: dict[str, list[dict]],
    ) -> list[dict]:
        """Fetch elestock rows for one corp, cached per collect() run."""
        if corp_code in cache:
            return cache[corp_code]

        rows: list[dict] = []
        if fixture is not None:
            payload = self._fixture_map(fixture, "elestock").get(corp_code)
            rows = self._normalize_history_payload(payload)
        elif self.api_key and corp_code:
            try:
                resp = self.session.get(
                    DART_ELESTOCK_URL,
                    params={"crtfc_key": self.api_key, "corp_code": corp_code},
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    if str(payload.get("status", "")) == "000":
                        rows = self._normalize_history_payload(payload)
            except Exception:
                # Enrichment is optional; the list row alone is enough.
                rows = []

        cache[corp_code] = rows
        return rows

    def _elestock_detail(
        self,
        item: dict,
        fixture: Optional[dict],
        cache: dict[str, list[dict]],
    ) -> Optional[dict]:
        """Return the elestock row matching this disclosure's rcept_no."""
        rcept_no = str(item.get("rcept_no", "")).strip()
        if not rcept_no:
            return None

        # Deterministic fixture support: a detail embedded in the list item.
        embedded = item.get("elestock_detail")
        if isinstance(embedded, dict):
            return embedded
        if isinstance(embedded, list):
            for row in embedded:
                if isinstance(row, dict) and str(row.get("rcept_no", "")).strip() == rcept_no:
                    return row

        corp_code = str(item.get("corp_code", "")).strip()
        if not corp_code:
            return None
        for row in self._elestock_rows_for_corp(corp_code, fixture, cache):
            if str(row.get("rcept_no", "")).strip() == rcept_no:
                return row
        return None

    # ------------------------------------------------------------------
    # Evidence text: confirmed facts only, never estimates.
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_fact(value: object) -> str:
        text = str(value or "").strip()
        return "" if text in {"", "-", "--"} else text

    def _build_facts(self, report_nm: str, detail: Optional[dict]) -> tuple[str, str]:
        """Return (evidence_text, representative reporter name or '')."""
        if not detail:
            return report_nm, ""

        repror = self._clean_fact(detail.get("repror"))
        ratio = self._clean_fact(detail.get("stkrt")) or self._clean_fact(detail.get("aggmt_stkrt"))
        ratio_irds = self._clean_fact(detail.get("stkrt_irds")) or self._clean_fact(detail.get("aggmt_stkrt_irds"))
        quantity = self._clean_fact(detail.get("stkqy")) or self._clean_fact(detail.get("aggmt_stkqy"))

        facts = [report_nm]
        if repror:
            facts.append(f"대표보고자 {repror}")
        if ratio:
            facts.append(f"보유비율 {ratio}%")
        if ratio_irds:
            facts.append(f"보유비율 증감 {ratio_irds}%p")
        if quantity:
            facts.append(f"보유주식수 {quantity}주")
        return " · ".join(facts), repror

    # Keys of the normalized majorstock item that evaluate_signal_score
    # consumes. The pipeline (five_pct_pricing) replays the scorer with
    # this exact input plus real prices, so the price-free collection
    # result and the price-enriched pipeline result can never drift apart
    # on the non-price factors.
    _SCORE_INPUT_KEYS = (
        "market", "rcept_no", "rcept_dt", "prev_rcept_dt", "first_entry_dt",
        "corp_code", "corp_name", "stock_code", "rpror_nm",
        "hold_stock_cnt", "stk_cnt_var", "hold_stock_rt", "stk_rt_var",
        "curr_purpose", "prev_purpose", "report_resn", "report_nm",
        "is_new_entry", "accum_count", "est_avg_price", "price_source",
        "current_price", "ownership_freshness",
    )

    # ------------------------------------------------------------------
    # Analysis payload carried on the event (consumed by export.py)
    # ------------------------------------------------------------------
    @staticmethod
    def _analysis_payload(processed: dict) -> dict:
        evaluation = processed.get("eval") or {}
        factor_scores = evaluation.get("factor_scores") or {}
        return {
            "score_input": {
                key: processed.get(key)
                for key in DartFivePctCollector._SCORE_INPUT_KEYS
            },
            "alpha_score": evaluation.get("score"),
            "score_breakdown": evaluation.get("breakdown") or [],
            "factor_scores": factor_scores,
            "investor_class": (evaluation.get("investor") or {}).get("label"),
            "investor_type": (evaluation.get("investor") or {}).get("type"),
            "purpose_prev": processed.get("prev_purpose"),
            "purpose_current": processed.get("curr_purpose"),
            "purpose_current_normalized": evaluation.get("curr_purpose_normalized"),
            "accumulation_count": processed.get("accum_count"),
            "freshness": evaluation.get("ownership_freshness"),
            "category": evaluation.get("category"),
            "categories": evaluation.get("categories") or [],
            "first_entry_dt": processed.get("first_entry_dt"),
            "hold_stock_rt": processed.get("hold_stock_rt"),
            "stk_rt_var": processed.get("stk_rt_var"),
            "stk_cnt_var": processed.get("stk_cnt_var"),
            "reporter": processed.get("rpror_nm"),
            "recent_accumulation_signal_active": evaluation.get(
                "recent_accumulation_signal_active"
            ),
        }

    @staticmethod
    def _parse_rcept_dt(value: object, fallback: datetime) -> datetime:
        text = str(value or "").replace("-", "")[:8]
        try:
            return datetime.strptime(text, "%Y%m%d") if len(text) == 8 else fallback
        except ValueError:
            return fallback

    def _event_from_processed(
        self,
        processed: dict,
        corp_meta: dict,
        since: datetime,
    ) -> RawEvent:
        """Build one event from a processed majorstock latest filing."""
        rcept_no = str(processed.get("rcept_no") or "").strip()
        ann_date = self._parse_rcept_dt(processed.get("rcept_dt"), since)
        report_nm = str(processed.get("report_nm") or "").strip() or "주식등의대량보유상황보고서"
        corp_name = str(processed.get("corp_name") or corp_meta.get("corp_name") or "").strip()
        ticker = str(processed.get("stock_code") or corp_meta.get("stock_code") or "").strip()
        repror = str(processed.get("rpror_nm") or "").strip()

        facts = [report_nm]
        if repror:
            facts.append(f"대표보고자 {repror}")
        hold_rt = processed.get("hold_stock_rt")
        if isinstance(hold_rt, (int, float)) and hold_rt:
            facts.append(f"보유비율 {hold_rt}%")
        rt_var = processed.get("stk_rt_var")
        if isinstance(rt_var, (int, float)) and rt_var:
            facts.append(f"보유비율 증감 {rt_var}%p")
        hold_cnt = self._clean_fact(processed.get("hold_stock_cnt"))
        if hold_cnt:
            facts.append(f"보유주식수 {hold_cnt}주")
        evidence_text = " · ".join(facts)

        event_name = f"{corp_name} {report_nm}".strip()
        if repror:
            event_name = f"{event_name} (대표보고자: {repror})"

        analysis = self._analysis_payload(processed)
        raw_payload = {
            "majorstock_latest": {
                key: value
                for key, value in processed.items()
                if key not in {"eval", "history"}
            },
            "history": processed.get("history") or [],
            "five_pct_analysis": analysis,
        }

        return RawEvent(
            source_name="DART_5PCT",
            source_kind="REGULATOR",
            source_event_uid=rcept_no or None,
            source_url=DART_DISCLOSURE_URL.format(rcept_no=rcept_no) if rcept_no else "",
            country="KR",
            primary_ticker=ticker,
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

    def _event_from_list_item(
        self,
        item: dict,
        fixture: Optional[dict],
        elestock_cache: dict[str, list[dict]],
        since: datetime,
    ) -> Optional[RawEvent]:
        """Degraded path: one event per list row with elestock enrichment."""
        report_nm = str(item.get("report_nm", "")).strip()
        ticker = str(item.get("stock_code", "") or "").strip()
        if not ticker:
            return None

        rcept_no = str(item.get("rcept_no", "")).strip()
        ann_date = self._parse_rcept_dt(item.get("rcept_dt"), since)

        detail = self._elestock_detail(item, fixture, elestock_cache)
        evidence_text, repror = self._build_facts(report_nm, detail)

        corp_name = str(item.get("corp_name", "")).strip()
        event_name = f"{corp_name} {report_nm}".strip()
        if repror:
            event_name = f"{event_name} (대표보고자: {repror})"

        raw_payload = dict(item)
        if detail is not None:
            raw_payload["elestock_detail"] = detail

        return RawEvent(
            source_name="DART_5PCT",
            source_kind="REGULATOR",
            source_event_uid=rcept_no or None,
            source_url=DART_DISCLOSURE_URL.format(rcept_no=rcept_no) if rcept_no else "",
            country="KR",
            primary_ticker=ticker,
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
        """Collect 5% large-shareholding filings received since `since`."""
        start_time = time.time()
        events: list[RawEvent] = []

        try:
            fixture = self._load_fixture()
            items = self._load_list_items(since, fixture)

            majorstock_cache: dict[str, list[dict]] = {}
            elestock_cache: dict[str, list[dict]] = {}

            # Group discovery rows by corp, preserving discovery order.
            corp_items: dict[str, list[dict]] = {}
            for item in items:
                report_nm = str(item.get("report_nm", "")).strip()
                if "대량보유" not in report_nm:
                    continue
                corp_code = str(item.get("corp_code", "")).strip()
                if not corp_code:
                    continue
                corp_items.setdefault(corp_code, []).append(item)

            for corp_code, corp_rows in list(corp_items.items())[:MAX_MAJORSTOCK_CORPS]:
                latest_item = max(
                    corp_rows, key=lambda row: str(row.get("rcept_no") or "")
                )
                corp_meta = {
                    "corp_name": str(latest_item.get("corp_name", "")).strip(),
                    "stock_code": str(latest_item.get("stock_code", "") or "").strip(),
                    "report_nm": str(latest_item.get("report_nm", "")).strip(),
                }

                major_rows = self._majorstock_rows_for_corp(
                    corp_code, fixture, majorstock_cache
                )
                processed_items: list[dict] = []
                if major_rows:
                    enriched_rows = []
                    for row in major_rows:
                        enriched = dict(row)
                        enriched.setdefault("corp_code", corp_code)
                        enriched.setdefault("corp_name", corp_meta["corp_name"])
                        if not enriched.get("stock_code"):
                            enriched["stock_code"] = corp_meta["stock_code"]
                        if str(enriched.get("rcept_no") or "") == str(
                            latest_item.get("rcept_no") or ""
                        ):
                            enriched["report_nm"] = (
                                corp_meta["report_nm"]
                                or enriched.get("report_nm")
                                or "주식등의대량보유상황보고서"
                            )
                        enriched_rows.append(enriched)
                    processed_items = process_majorstock_history(
                        enriched_rows,
                        min_rcept_date=since.strftime("%Y%m%d"),
                    )

                if processed_items:
                    for processed in processed_items:
                        if not str(
                            processed.get("stock_code") or corp_meta["stock_code"]
                        ).strip():
                            continue
                        events.append(
                            self._event_from_processed(processed, corp_meta, since)
                        )
                else:
                    # Degrade: majorstock had nothing usable for this corp.
                    for item in corp_rows:
                        event = self._event_from_list_item(
                            item, fixture, elestock_cache, since
                        )
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
