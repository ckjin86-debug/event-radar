"""Dual trading-day backtest for 5% filings (original computeEventStudy).

The pure-calculation cases pin the original background.js
``computeEventStudyFromCandles`` semantics: candle-index (trading-day)
horizons, pending horizons as None (never 0%), the latest/first-entry
anchors kept strictly separate, and Max Run-up / MDD from the 60
trading-day window's highs/lows. The enrichment/export/pipeline cases
pin the wiring: analysis["backtest"] attached only when a real price
frame exists, lifted verbatim into five_pct.json.
"""

import json
from datetime import date, datetime

import pandas as pd

from event_radar.collectors.dart_five_pct import DartFivePctCollector
from event_radar.export import export_site_data
from event_radar.five_pct_backtest import (
    compute_event_study_from_candles,
    enrich_five_pct_backtest_event,
    enrich_five_pct_backtests,
)
from event_radar.five_pct_rules import evaluate_signal_score
from event_radar.models import Event, RawEvent
from event_radar.pipeline import PipelineConfig, run_pipeline


# ----------------------------------------------------------------------
# Pure calculation: 90 business days, close = 1000 + 10*i, high/low ±5,
# except a high spike at idx30 (2000) and a low dip at idx40 (500).
# ----------------------------------------------------------------------
DAYS = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-08-03", periods=90)]
FIRST_IDX = 10
RCEPT_IDX = 70
REF = date(2026, 12, 31)


def _study_candles() -> list[dict]:
    candles = []
    for i, day in enumerate(DAYS):
        close = 1000 + 10 * i
        high = 2000 if i == 30 else close + 5
        low = 500 if i == 40 else close - 5
        candles.append({
            "date": date.fromisoformat(day),
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000,
        })
    return candles


def test_dual_anchors_are_computed_separately():
    result = compute_event_study_from_candles(
        _study_candles(), DAYS[RCEPT_IDX], DAYS[FIRST_IDX], reference_date=REF
    )

    latest = result["latest"]
    assert latest["baseDate"] == DAYS[RCEPT_IDX]
    assert latest["marketBaseDate"] == DAYS[RCEPT_IDX]
    assert latest["basePrice"] == 1700
    assert latest["availTradingDays"] == 19
    assert latest["elapsedDays"] == (REF - date.fromisoformat(DAYS[RCEPT_IDX])).days
    assert latest["d5"] == 2.9            # close[75]=1750 vs 1700
    assert latest["d20"] is None         # only 19 trading days elapsed
    assert latest["d60"] is None
    assert latest["cumReturn"] == 11.2   # last close 1890 vs 1700
    assert latest["maxRunup"] == 11.5    # window high 1895
    assert latest["mdd"] == -0.3         # window low 1695

    first = result["firstEntry"]
    assert first["baseDate"] == DAYS[FIRST_IDX]
    assert first["marketBaseDate"] == DAYS[FIRST_IDX]
    assert first["basePrice"] == 1100
    assert first["availTradingDays"] == 79
    assert first["d5"] == 4.5            # close[15]=1150
    assert first["d20"] == 18.2          # close[30]=1300
    assert first["d60"] == 54.5          # close[70]=1700
    assert first["cumReturn"] == 71.8    # last close 1890
    assert first["maxRunup"] == 81.8     # spike high 2000 at idx30
    assert first["mdd"] == -54.5         # dip low 500 at idx40
    assert first["isSameAsLatest"] is False


def test_base_candle_is_first_on_or_after_weekend_anchor():
    # 2026-08-08 is a Saturday; the base candle is Monday idx5.
    result = compute_event_study_from_candles(
        _study_candles(), "2026-08-08", None, reference_date=REF
    )
    assert result["latest"]["baseDate"] == "2026-08-08"
    assert result["latest"]["marketBaseDate"] == DAYS[5]
    assert result["latest"]["basePrice"] == 1050


def test_filing_on_last_candle_has_all_horizons_pending():
    result = compute_event_study_from_candles(
        _study_candles(), DAYS[-1], None, reference_date=REF
    )
    latest = result["latest"]
    assert latest["availTradingDays"] == 0
    assert latest["d5"] is None and latest["d20"] is None and latest["d60"] is None
    # Same candle for base and latest: cum 0.0 is a real measurement,
    # and Max/MDD use the original's avail<1 stub of 0.0.
    assert latest["cumReturn"] == 0.0
    assert latest["maxRunup"] == 0.0
    assert latest["mdd"] == 0.0
    assert result["firstEntry"]["isSameAsLatest"] is True


def test_first_entry_defaults_to_filing_date():
    candles = _study_candles()
    result = compute_event_study_from_candles(
        candles, DAYS[RCEPT_IDX], None, reference_date=REF
    )
    first = result["firstEntry"]
    assert first["isSameAsLatest"] is True
    assert first["baseDate"] == DAYS[RCEPT_IDX]
    assert first["d5"] == result["latest"]["d5"]
    assert first["cumReturn"] == result["latest"]["cumReturn"]


def test_latest_after_last_candle_falls_back_to_stub_but_first_entry_is_real():
    result = compute_event_study_from_candles(
        _study_candles(), "2027-02-01", DAYS[FIRST_IDX], reference_date=REF
    )
    latest = result["latest"]
    assert latest["baseDate"] == "2027-02-01"
    assert latest["availTradingDays"] == 0
    assert latest["cumReturn"] == 0
    assert latest["d5"] is None and latest["d20"] is None and latest["d60"] is None
    assert latest["maxRunup"] is None
    first = result["firstEntry"]
    assert first["baseDate"] == DAYS[FIRST_IDX]
    assert first["d20"] == 18.2
    assert first["isSameAsLatest"] is False


def test_no_candles_or_no_anchor_returns_fallback():
    assert compute_event_study_from_candles([], DAYS[0]) is None
    assert compute_event_study_from_candles(None, DAYS[0]) is None
    marker = {"latest": {"baseDate": "kept"}}
    assert compute_event_study_from_candles([], DAYS[0], fallback=marker) is marker
    # Both anchors beyond the last candle and no fallback.
    assert compute_event_study_from_candles(
        _study_candles(), "2027-02-01", "2027-03-01"
    ) is None


def test_returns_round_half_up_to_one_decimal():
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-10-05", periods=10)]
    candles = [
        {"date": day, "high": 800, "low": 800, "close": 800, "volume": 1}
        for day in days
    ]
    candles[5]["close"] = 810  # +1.25% -> JS toFixed(1) "1.3"
    result = compute_event_study_from_candles(candles, days[0])
    assert result["latest"]["d5"] == 1.3


def test_accepts_string_dates_and_dataframe_input():
    frame = pd.DataFrame(_study_candles())
    result = compute_event_study_from_candles(
        frame, DAYS[RCEPT_IDX], DAYS[FIRST_IDX], reference_date=REF
    )
    assert result["latest"]["cumReturn"] == 11.2

    string_candles = [
        {**c, "date": c["date"].isoformat()} for c in _study_candles()
    ]
    result = compute_event_study_from_candles(
        string_candles, DAYS[RCEPT_IDX], DAYS[FIRST_IDX], reference_date=REF
    )
    assert result["firstEntry"]["maxRunup"] == 81.8


# ----------------------------------------------------------------------
# Enrichment
# ----------------------------------------------------------------------
AS_OF = date.fromisoformat(DAYS[-1])


def _study_frame() -> pd.DataFrame:
    return pd.DataFrame(_study_candles())


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
        "rcept_dt": DAYS[RCEPT_IDX],
        "prev_rcept_dt": None,
        "first_entry_dt": DAYS[FIRST_IDX],
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
        "is_new_entry": False,
        "accum_count": 1,
        "est_avg_price": None,
        "price_source": None,
        "current_price": None,
        "ownership_freshness": "CURRENT",
    }
    base.update(overrides)
    return base


def _analysis(score_input: dict) -> dict:
    processed = {
        **score_input,
        "eval": evaluate_signal_score(dict(score_input)),
        "history": [],
    }
    return DartFivePctCollector._analysis_payload(processed)


def _five_event(analysis: dict, *, event_id: str = "five-bt-1") -> Event:
    rcept = date.fromisoformat(DAYS[RCEPT_IDX])
    return Event(
        event_id=event_id,
        country="KR",
        event_type="5PCT_OWNERSHIP",
        event_name="테스트기업 주식등의대량보유상황보고서(일반) (대표보고자: 홍길동)",
        primary_ticker="123456",
        primary_company="테스트기업",
        announced_at=datetime(rcept.year, rcept.month, rcept.day),
        event_date=rcept,
        event_time_context="DATE_ONLY",
        status="CONFIRMED",
        source_kind="REGULATOR",
        source_name="DART_5PCT",
        source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261026000117",
        source_event_uid="20261026000117",
        evidence_text="주식등의대량보유상황보고서(일반) · 대표보고자 홍길동 · 보유비율 6.2%",
        ingest_mode="AUTO",
        first_seen_at=datetime(rcept.year, rcept.month, rcept.day),
        last_seen_at=datetime(rcept.year, rcept.month, rcept.day),
        needs_review=False,
        five_pct_analysis=analysis,
    )


def test_enrichment_attaches_dual_backtest():
    event = _five_event(_analysis(_score_input()))
    provider = StubPriceProvider(_study_frame())

    enriched = enrich_five_pct_backtest_event(event, provider, AS_OF)

    backtest = enriched.five_pct_analysis["backtest"]
    assert backtest["latest"]["baseDate"] == DAYS[RCEPT_IDX]
    assert backtest["latest"]["cumReturn"] == 11.2
    assert backtest["latest"]["d20"] is None
    assert backtest["firstEntry"]["baseDate"] == DAYS[FIRST_IDX]
    assert backtest["firstEntry"]["maxRunup"] == 81.8
    assert backtest["firstEntry"]["isSameAsLatest"] is False
    assert backtest["latest"]["elapsedDays"] == (
        AS_OF - date.fromisoformat(DAYS[RCEPT_IDX])
    ).days
    # The rest of the analysis is untouched.
    assert enriched.five_pct_analysis["alpha_score"] == (
        event.five_pct_analysis["alpha_score"]
    )
    assert provider.calls == ["123456"]


def test_enrichment_without_price_frame_keeps_no_backtest():
    analysis = _analysis(_score_input())
    event = _five_event(analysis)

    empty = enrich_five_pct_backtest_event(event, StubPriceProvider(None), AS_OF)
    assert empty.five_pct_analysis == analysis
    assert "backtest" not in empty.five_pct_analysis

    failing = enrich_five_pct_backtest_event(
        event, StubPriceProvider(_study_frame(), raises=True), AS_OF
    )
    assert failing.five_pct_analysis == analysis


def test_enrichment_works_for_legacy_analysis_without_score_input():
    rcept = date.fromisoformat(DAYS[RCEPT_IDX])
    legacy = {"alpha_score": 3, "first_entry_dt": DAYS[FIRST_IDX]}
    event = _five_event(legacy)

    enriched = enrich_five_pct_backtest_event(
        event, StubPriceProvider(_study_frame()), AS_OF
    )

    backtest = enriched.five_pct_analysis["backtest"]
    assert backtest["latest"]["baseDate"] == rcept.isoformat()
    assert backtest["firstEntry"]["baseDate"] == DAYS[FIRST_IDX]


def test_enrich_list_shares_one_fetch_per_ticker_and_skips_others():
    first = _five_event(_analysis(_score_input()), event_id="five-bt-a")
    second = _five_event(_analysis(_score_input()), event_id="five-bt-b")
    other = first.model_copy(update={
        "event_id": "other-1", "event_type": "CAPEX_FINANCING",
        "source_name": "DART", "five_pct_analysis": {},
    })
    provider = StubPriceProvider(_study_frame())

    result = enrich_five_pct_backtests([other, first, second], provider, AS_OF)

    assert result[0] is other
    assert "backtest" in result[1].five_pct_analysis
    assert "backtest" in result[2].five_pct_analysis
    assert provider.calls == ["123456"]


def test_enriched_backtest_exports_verbatim_and_plain_row_has_no_key(tmp_path):
    enriched = enrich_five_pct_backtest_event(
        _five_event(_analysis(_score_input())),
        StubPriceProvider(_study_frame()),
        AS_OF,
    )
    plain = _five_event(_analysis(_score_input()), event_id="five-bt-plain")

    export_site_data(
        events=[enriched, plain],
        revisions=[],
        event_securities={},
        event_scores={},
        event_returns_df=None,
        strategy_results={},
        backtest_summaries={},
        output_dir=tmp_path,
        collector_status={},
        now=datetime(AS_OF.year, AS_OF.month, AS_OF.day, 10, 0),
    )

    rows = {
        row["event_id"]: row
        for row in json.loads((tmp_path / "five_pct.json").read_text(encoding="utf-8"))
    }
    assert rows["five-bt-1"]["backtest"] == enriched.five_pct_analysis["backtest"]
    assert rows["five-bt-1"]["backtest"]["latest"]["d5"] == 2.9
    assert rows["five-bt-1"]["backtest"]["firstEntry"]["mdd"] == -54.5
    assert "backtest" not in rows["five-bt-plain"]


# ----------------------------------------------------------------------
# Pipeline integration: collector analysis -> backtest -> five_pct.json
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
        rcept = date.fromisoformat(DAYS[RCEPT_IDX])
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
                announced_at=datetime(rcept.year, rcept.month, rcept.day),
                event_date=rcept,
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
        frame = _study_frame()
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


def _run_mock_pipeline(tmp_path, *, skip_price_fetch: bool):
    data_dir, site_dir, config_dir = _pipeline_dirs(tmp_path)
    provider = AnyTickerPriceProvider()
    cfg = PipelineConfig(
        data_dir=data_dir, site_dir=site_dir, config_dir=config_dir,
        price_provider=provider,
    )
    run_pipeline(
        collectors=[MockFivePctCollector()],
        config=cfg,
        now=datetime(AS_OF.year, AS_OF.month, AS_OF.day, 10, 0),
        skip_price_fetch=skip_price_fetch,
    )
    rows = json.loads((site_dir / "data" / "five_pct.json").read_text(encoding="utf-8"))
    return rows, provider


def test_pipeline_attaches_backtest_end_to_end(tmp_path):
    rows, provider = _run_mock_pipeline(tmp_path, skip_price_fetch=False)

    assert len(rows) == 1
    backtest = rows[0]["backtest"]
    assert backtest["latest"]["baseDate"] == DAYS[RCEPT_IDX]
    assert backtest["latest"]["cumReturn"] == 11.2
    assert backtest["latest"]["d20"] is None
    assert backtest["firstEntry"]["baseDate"] == DAYS[FIRST_IDX]
    assert backtest["firstEntry"]["d60"] == 54.5
    assert backtest["firstEntry"]["maxRunup"] == 81.8
    assert "123456" in provider.calls


def test_pipeline_skip_price_fetch_has_no_backtest(tmp_path):
    rows, provider = _run_mock_pipeline(tmp_path, skip_price_fetch=True)

    assert len(rows) == 1
    assert "backtest" not in rows[0]
    assert provider.calls == []
