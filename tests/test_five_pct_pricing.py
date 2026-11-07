"""VWAP estimation (Priority 3) + pipeline price enrichment for 5% filings.

The VWAP cases pin the original background.js
``computeAcquisitionWindowVWAP`` semantics; the enrichment cases pin the
original enrichment batch: latest close as current price, VWAP-filled
average price, scorer replayed on the identical score_input so only the
S6 price entries change.
"""

import json
from datetime import date, datetime

import pandas as pd

from event_radar.collectors.dart_five_pct import DartFivePctCollector
from event_radar.export import export_site_data
from event_radar.five_pct_pricing import enrich_five_pct_event, enrich_five_pct_prices
from event_radar.five_pct_rules import compute_acquisition_window_vwap, evaluate_signal_score
from event_radar.models import Event, RawEvent
from event_radar.pipeline import PipelineConfig, run_pipeline


# ----------------------------------------------------------------------
# VWAP unit tests
# ----------------------------------------------------------------------
def _candle(day: str, close: float, *, high=None, low=None, volume=1000) -> dict:
    return {
        "date": day,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
        "volume": volume,
    }


def _business_days(start: str, count: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start=start, periods=count)]


def test_vwap_default_window_is_seven_trading_days_before_filing():
    days = _business_days("2026-10-05", 12)  # last = 2026-10-20
    candles = [_candle(d, 999_999 if i < 4 else 100) for i, d in enumerate(days)]

    result = compute_acquisition_window_vwap(candles, days[-1], None)

    # Window = candles[end-7 .. end] (8 candles), junk before it excluded.
    assert result == {
        "vwap": 100,
        "start_date": days[4],
        "end_date": days[-1],
    }


def test_vwap_uses_prev_filing_candle_within_40_trading_days():
    days = _business_days("2026-09-01", 30)
    candles = [_candle(d, 77_777 if i < 15 else 100) for i, d in enumerate(days)]

    result = compute_acquisition_window_vwap(candles, days[29], days[15])

    assert result["vwap"] == 100
    assert result["start_date"] == days[15]
    assert result["end_date"] == days[29]


def test_vwap_prev_filing_beyond_40_trading_days_falls_back_to_default_window():
    days = _business_days("2026-08-03", 60)
    candles = [_candle(d, 77_777 if i < 52 else 100) for i, d in enumerate(days)]

    result = compute_acquisition_window_vwap(candles, days[59], days[5])

    # 59 - 5 = 54 > 40 trading days: prev anchor rejected, default window.
    assert result["vwap"] == 100
    assert result["start_date"] == days[52]
    assert result["end_date"] == days[59]


def test_vwap_prev_filing_at_or_after_filing_candle_falls_back():
    days = _business_days("2026-10-05", 12)
    candles = [_candle(d, 100) for d in days]

    same_day = compute_acquisition_window_vwap(candles, days[-1], days[-1])
    assert same_day["start_date"] == days[4]

    after = compute_acquisition_window_vwap(candles, days[-1], "2027-01-04")
    assert after["start_date"] == days[4]


def test_vwap_typical_price_volume_weighting_and_half_up_rounding():
    # A: typical (100+80+90)/3 = 90, volume 3
    # B: typical (126+106+116)/3 = 116, volume 0 -> weight 1
    # VWAP = (90*3 + 116*1) / 4 = 96.5 -> KR half-up 97 (JS Math.round)
    candles = [
        {"date": "2026-10-19", "high": 100, "low": 80, "close": 90, "volume": 3},
        {"date": "2026-10-20", "high": 126, "low": 106, "close": 116, "volume": 0},
    ]

    kr = compute_acquisition_window_vwap(candles, "2026-10-20", None)
    assert kr["vwap"] == 97

    us = compute_acquisition_window_vwap(candles, "2026-10-20", None, is_us=True)
    assert us["vwap"] == 96.5


def test_vwap_missing_high_low_fall_back_to_close():
    candles = [{"date": "2026-10-20", "high": None, "low": 0, "close": 12_345, "volume": 100}]
    result = compute_acquisition_window_vwap(candles, "2026-10-20", None)
    assert result["vwap"] == 12_345


def test_vwap_accepts_price_provider_dataframe():
    days = _business_days("2026-10-05", 12)
    frame = pd.DataFrame({
        "date": [date.fromisoformat(d) for d in days],
        "open": [100.0] * 12,
        "high": [100.0] * 12,
        "low": [100.0] * 12,
        "close": [100.0] * 12,
        "adj_close": [100.0] * 12,
        "volume": [1000] * 12,
    })

    result = compute_acquisition_window_vwap(frame, days[-1], None)
    assert result["vwap"] == 100
    assert result["end_date"] == days[-1]


def test_vwap_empty_candles_and_filing_after_last_candle():
    assert compute_acquisition_window_vwap([], "2026-10-20", None) is None
    assert compute_acquisition_window_vwap(None, "2026-10-20", None) is None

    days = _business_days("2026-10-05", 12)
    candles = [_candle(d, 100) for d in days]
    result = compute_acquisition_window_vwap(candles, "2026-12-31", None)
    assert result["end_date"] == days[-1]
    assert result["start_date"] == days[4]


# ----------------------------------------------------------------------
# Enrichment tests
# ----------------------------------------------------------------------
AS_OF = date(2026, 11, 2)
_FRAME_DAYS = [
    date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14),
    date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 19),
    date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22),
    date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 27),
    date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30),
    date(2026, 11, 2),
]
_RCEPT = date(2026, 10, 26)


def _frame(last_close: float, window_close: float = 10_000) -> pd.DataFrame:
    rows = []
    for d in _FRAME_DAYS:
        close = window_close if d <= _RCEPT else last_close
        rows.append({
            "date": d, "open": close, "high": close, "low": close,
            "close": close, "adj_close": close, "volume": 1000,
        })
    return pd.DataFrame(rows)


class StubPriceProvider:
    def __init__(self, frame=None, *, raises: bool = False):
        self.frame = frame
        self.raises = raises
        self.calls: list[str] = []

    def history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        self.calls.append(ticker)
        if self.raises:
            raise RuntimeError("provider down")
        if self.frame is None:
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "adj_close", "volume"]
            )
        frame = self.frame
        return frame[(frame["date"] >= start) & (frame["date"] <= end)].reset_index(drop=True)


def _score_input(**overrides) -> dict:
    base = {
        "market": "KR",
        "rcept_no": "20261026000117",
        "rcept_dt": "2026-10-26",
        "prev_rcept_dt": None,
        "first_entry_dt": "2026-10-26",
        "corp_code": "00100000",
        "corp_name": "테스트기업",
        "stock_code": "123456",
        "rpror_nm": "홍길동",
        "hold_stock_cnt": "1,500,000",
        "stk_cnt_var": "+500,000",
        "hold_stock_rt": 6.2,
        "stk_rt_var": 2.1,
        "curr_purpose": "일반투자",
        "prev_purpose": "단순투자",
        "report_resn": "장내매수",
        "report_nm": "주식등의대량보유상황보고서(일반)",
        "is_new_entry": True,
        "accum_count": 0,
        "est_avg_price": None,
        "price_source": None,
        "current_price": None,
        "ownership_freshness": "CURRENT",
    }
    base.update(overrides)
    return base


def _analysis(score_input: dict) -> dict:
    """Build the analysis exactly the way the collector does."""
    processed = {
        **score_input,
        "eval": evaluate_signal_score(dict(score_input)),
        "history": [],
    }
    return DartFivePctCollector._analysis_payload(processed)


def _five_event(analysis: dict) -> Event:
    return Event(
        event_id="five-price-1",
        country="KR",
        event_type="5PCT_OWNERSHIP",
        event_name="테스트기업 주식등의대량보유상황보고서(일반) (대표보고자: 홍길동)",
        primary_ticker="123456",
        primary_company="테스트기업",
        announced_at=datetime(2026, 10, 26),
        event_date=_RCEPT,
        event_time_context="DATE_ONLY",
        status="CONFIRMED",
        source_kind="REGULATOR",
        source_name="DART_5PCT",
        source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261026000117",
        source_event_uid="20261026000117",
        evidence_text="주식등의대량보유상황보고서(일반) · 대표보고자 홍길동 · 보유비율 6.2%",
        ingest_mode="AUTO",
        first_seen_at=datetime(2026, 10, 26),
        last_seen_at=datetime(2026, 10, 26),
        needs_review=False,
        five_pct_analysis=analysis,
    )


def _non_price_entries(breakdown: list[dict]) -> list[dict]:
    return [
        b for b in breakdown
        if "평단" not in b["strategy"] and "안전마진" not in b["strategy"]
    ]


def test_enrichment_deep_safety_margin_adds_two_points():
    score_input = _score_input()
    analysis = _analysis(score_input)
    baseline_alpha = analysis["alpha_score"]
    event = _five_event(analysis)
    provider = StubPriceProvider(_frame(last_close=8_800))

    enriched = enrich_five_pct_event(event, provider, AS_OF)
    result = enriched.five_pct_analysis

    # gap = 8800/10000 - 1 = -12.0% -> deep safety margin +2
    assert result["alpha_score"] == baseline_alpha + 2
    assert result["factor_scores"]["s6_price_margin"] == (
        analysis["factor_scores"]["s6_price_margin"] + 2
    )
    assert result["est_avg_price"] == 10_000
    assert result["current_price"] == 8_800
    assert result["price_gap_pct"] == -12.0
    assert result["price_source"] == (
        "VWAP_ESTIMATE: 2026-10-15~2026-10-26 매집기간 일봉 VWAP"
    )
    margin = [b for b in result["score_breakdown"] if b["strategy"] == "전략 6 (세력 평단 안전마진)"]
    assert len(margin) == 1 and margin[0]["points"] == 2
    assert not any("미산출" in b["reason"] for b in result["score_breakdown"])
    # Non-price breakdown is reproduced identically, in the same order.
    assert _non_price_entries(result["score_breakdown"]) == _non_price_entries(
        analysis["score_breakdown"]
    )
    # The stored score_input stays price-free so re-runs re-derive cleanly.
    assert result["score_input"]["est_avg_price"] is None
    assert result["score_input"]["current_price"] is None


def test_enrichment_safety_margin_adds_one_point():
    analysis = _analysis(_score_input())
    event = _five_event(analysis)
    provider = StubPriceProvider(_frame(last_close=9_400))

    enriched = enrich_five_pct_event(event, provider, AS_OF)
    result = enriched.five_pct_analysis

    # gap = -6.0% -> safety margin +1
    assert result["price_gap_pct"] == -6.0
    assert result["alpha_score"] == analysis["alpha_score"] + 1
    margin = [b for b in result["score_breakdown"] if b["strategy"] == "전략 6 (세력 평단 하회)"]
    assert len(margin) == 1 and margin[0]["points"] == 1


def test_enrichment_mezzanine_filing_gets_prices_but_no_margin_points():
    score_input = _score_input(
        report_resn="제3회차 전환사채 인수계약에 따른 신규보고",
        report_nm="주식등의대량보유상황보고서(일반)",
    )
    analysis = _analysis(score_input)
    event = _five_event(analysis)
    provider = StubPriceProvider(_frame(last_close=8_800))

    enriched = enrich_five_pct_event(event, provider, AS_OF)
    result = enriched.five_pct_analysis

    # Prices are attached (as in the original batch) but the CB/mezzanine
    # exclusion keeps every margin point out of the score.
    assert result["est_avg_price"] == 10_000
    assert result["current_price"] == 8_800
    assert result["price_gap_pct"] == -12.0
    assert result["alpha_score"] == analysis["alpha_score"]
    assert result["factor_scores"]["s6_price_margin"] == (
        analysis["factor_scores"]["s6_price_margin"]
    )
    assert not any(
        b["strategy"] in {"전략 6 (세력 평단 안전마진)", "전략 6 (세력 평단 하회)"}
        for b in result["score_breakdown"]
    )


def test_enrichment_without_price_frame_keeps_uncomputed_state():
    analysis = _analysis(_score_input())
    event = _five_event(analysis)

    empty = enrich_five_pct_event(event, StubPriceProvider(None), AS_OF)
    assert empty.five_pct_analysis == analysis
    assert any("미산출" in b["reason"] for b in empty.five_pct_analysis["score_breakdown"])

    failing = enrich_five_pct_event(
        event, StubPriceProvider(_frame(8_800), raises=True), AS_OF
    )
    assert failing.five_pct_analysis == analysis


def test_enrichment_without_score_input_is_untouched():
    legacy = {"alpha_score": 3, "score_breakdown": [], "investor_class": "행동주의"}
    event = _five_event(legacy)
    provider = StubPriceProvider(_frame(8_800))

    enriched = enrich_five_pct_event(event, provider, AS_OF)

    assert enriched.five_pct_analysis == legacy
    assert provider.calls == []


def test_enriched_analysis_exports_price_fields(tmp_path):
    analysis = _analysis(_score_input())
    event = enrich_five_pct_event(
        _five_event(analysis), StubPriceProvider(_frame(8_800)), AS_OF
    )
    plain = _five_event(_analysis(_score_input())).model_copy(
        update={"event_id": "five-price-plain"}
    )

    export_site_data(
        events=[event, plain],
        revisions=[],
        event_securities={},
        event_scores={},
        event_returns_df=None,
        strategy_results={},
        backtest_summaries={},
        output_dir=tmp_path,
        collector_status={},
        now=datetime(2026, 11, 2, 10, 0),
    )

    rows = {
        row["event_id"]: row
        for row in json.loads((tmp_path / "five_pct.json").read_text(encoding="utf-8"))
    }
    priced = rows["five-price-1"]
    assert priced["est_avg_price"] == 10_000
    assert priced["current_price"] == 8_800
    assert priced["price_gap_pct"] == -12.0
    assert priced["price_source"].startswith("VWAP_ESTIMATE:")
    unpriced = rows["five-price-plain"]
    assert "est_avg_price" not in unpriced
    assert "current_price" not in unpriced
    assert "price_gap_pct" not in unpriced
    assert "price_source" not in unpriced


# ----------------------------------------------------------------------
# Pipeline integration: collector analysis -> enrichment -> five_pct.json
# ----------------------------------------------------------------------
class MockFivePctCollector:
    source_name = "DART_5PCT"

    def collect(self, since: datetime) -> list[RawEvent]:
        score_input = _score_input()
        processed = {
            **score_input,
            "eval": evaluate_signal_score(dict(score_input)),
            "history": [],
        }
        return [
            RawEvent(
                source_name="DART_5PCT",
                source_kind="REGULATOR",
                source_event_uid="20261026000117",
                source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261026000117",
                country="KR",
                primary_ticker="123456",
                primary_company="테스트기업",
                event_type="5PCT_OWNERSHIP",
                event_name="테스트기업 주식등의대량보유상황보고서(일반) (대표보고자: 홍길동)",
                announced_at=datetime(2026, 10, 26),
                event_date=_RCEPT,
                status="CONFIRMED",
                evidence_text="주식등의대량보유상황보고서(일반) · 대표보고자 홍길동 · 보유비율 6.2%",
                raw_payload={
                    "five_pct_analysis": DartFivePctCollector._analysis_payload(processed)
                },
            )
        ]


class AnyTickerPriceProvider(StubPriceProvider):
    def history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        self.calls.append(ticker)
        frame = _frame(8_800)
        return frame[(frame["date"] >= start) & (frame["date"] <= end)].reset_index(drop=True)


def _pipeline_dirs(tmp_path):
    data_dir = tmp_path / "data"
    site_dir = tmp_path / "site"
    config_dir = tmp_path / "config"
    (data_dir / "canonical").mkdir(parents=True)
    (data_dir / "derived").mkdir(parents=True)
    (site_dir / "data").mkdir(parents=True)
    config_dir.mkdir(parents=True)
    return data_dir, site_dir, config_dir


def test_pipeline_enriches_five_pct_prices_end_to_end(tmp_path):
    data_dir, site_dir, config_dir = _pipeline_dirs(tmp_path)
    baseline_alpha = _analysis(_score_input())["alpha_score"]
    provider = AnyTickerPriceProvider()
    cfg = PipelineConfig(
        data_dir=data_dir, site_dir=site_dir, config_dir=config_dir,
        price_provider=provider,
    )

    run_pipeline(
        collectors=[MockFivePctCollector()],
        config=cfg,
        now=datetime(2026, 11, 2, 10, 0),
        skip_price_fetch=False,
    )

    rows = json.loads((site_dir / "data" / "five_pct.json").read_text(encoding="utf-8"))
    assert len(rows) == 1
    row = rows[0]
    assert row["alpha_score"] == baseline_alpha + 2
    assert row["event_score"] == baseline_alpha + 2
    assert row["est_avg_price"] == 10_000
    assert row["current_price"] == 8_800
    assert row["price_gap_pct"] == -12.0
    assert row["price_source"] == (
        "VWAP_ESTIMATE: 2026-10-15~2026-10-26 매집기간 일봉 VWAP"
    )
    assert not any("미산출" in b["reason"] for b in row["score_breakdown"])
    assert "123456" in provider.calls


def test_pipeline_skip_price_fetch_keeps_uncomputed_state(tmp_path):
    data_dir, site_dir, config_dir = _pipeline_dirs(tmp_path)
    provider = AnyTickerPriceProvider()
    cfg = PipelineConfig(
        data_dir=data_dir, site_dir=site_dir, config_dir=config_dir,
        price_provider=provider,
    )

    run_pipeline(
        collectors=[MockFivePctCollector()],
        config=cfg,
        now=datetime(2026, 11, 2, 10, 0),
        skip_price_fetch=True,
    )

    rows = json.loads((site_dir / "data" / "five_pct.json").read_text(encoding="utf-8"))
    assert len(rows) == 1
    row = rows[0]
    assert "est_avg_price" not in row
    assert "current_price" not in row
    assert "price_gap_pct" not in row
    assert "price_source" not in row
    assert any("미산출" in b["reason"] for b in row["score_breakdown"])
    assert "123456" not in provider.calls


def test_enrich_five_pct_prices_skips_other_events():
    analysis = _analysis(_score_input())
    filing = _five_event(analysis)
    other = filing.model_copy(update={
        "event_id": "other-1", "event_type": "CAPEX_FINANCING",
        "source_name": "DART", "five_pct_analysis": {},
    })
    provider = StubPriceProvider(_frame(8_800))

    result = enrich_five_pct_prices([other, filing], provider, AS_OF)

    assert result[0] is other
    assert result[1].five_pct_analysis["price_gap_pct"] == -12.0
