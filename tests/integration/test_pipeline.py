from datetime import datetime, date
from pathlib import Path
import json
import pandas as pd
import pytest
from event_radar.models import RawEvent
from event_radar.pipeline import run_pipeline, PipelineConfig
from event_radar.collectors.base import Collector


class MockFailingCollector:
    source_name = "FAILING_COLLECTOR"

    def collect(self, since: datetime) -> list[RawEvent]:
        raise RuntimeError("Network down or timeout")


class MockSuccessfulCollector:
    source_name = "SUCCESS_COLLECTOR"

    def collect(self, since: datetime) -> list[RawEvent]:
        return [
            RawEvent(
                source_name="SUCCESS_COLLECTOR",
                source_kind="COMPANY",
                source_event_uid="SUCCESS_01",
                source_url="https://example.com/notice/1",
                country="KR",
                primary_ticker="005930",
                primary_company="삼성전자",
                event_type="BONUS_ISSUE",
                event_name="삼성전자 무상증자 공시",
                announced_at=datetime(2026, 11, 1),
                event_date=date(2026, 11, 20),
                status="CONFIRMED",
            )
        ]


class MockHistoricalCollector:
    source_name = "HISTORICAL_COLLECTOR"

    def collect(self, since: datetime) -> list[RawEvent]:
        return [
            RawEvent(
                source_name="HISTORICAL_COLLECTOR",
                source_kind="COMPANY",
                source_event_uid="HIST_01",
                source_url="https://example.com/notice/hist-1",
                country="KR",
                primary_ticker="005930",
                primary_company="삼성전자",
                event_type="BONUS_ISSUE",
                event_name="삼성전자 과거 무상증자",
                announced_at=datetime(2026, 8, 1),
                event_date=date(2026, 9, 15),
                status="CONFIRMED",
            )
        ]


class MockLegacyNoiseCollector:
    source_name = "DART"

    def collect(self, since: datetime) -> list[RawEvent]:
        return [
            RawEvent(
                source_name="DART",
                source_kind="REGULATOR",
                source_event_uid="LEGACY_RIGHTS_01",
                source_url="https://example.com/dart/noise",
                country="KR",
                primary_ticker="123456",
                primary_company="노이즈기업",
                event_type="RIGHTS_ISSUE",
                event_name="노이즈기업 유상증자결정",
                announced_at=datetime(2026, 10, 1),
                event_date=date(2026, 10, 1),
                status="CONFIRMED",
            )
        ]


class MockFutureHyundaiCollector:
    source_name = "NEWS_FUTURE"

    def collect(self, since: datetime) -> list[RawEvent]:
        return [
            RawEvent(
                source_name="NEWS_FUTURE",
                source_kind="SECONDARY",
                source_event_uid="HYUNDAI_AI_VALLEY",
                source_url="https://example.com/hyundai-ai-valley",
                country="KR",
                primary_ticker="",
                primary_company="현대차그룹",
                event_type="CAPEX",
                event_name="현대차그룹 새만금 AI 밸리 내년 3월 착공",
                announced_at=datetime(2026, 10, 30, 11, 38),
                event_date=date(2027, 3, 1),
                date_precision="MONTH",
                window_start=date(2027, 3, 1),
                window_end=date(2027, 3, 31),
                status="EXPECTED",
            )
        ]


class DeterministicPriceProvider:
    def __init__(self):
        self.calls: list[tuple[str, date, date]] = []

    def history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        self.calls.append((ticker, start, end))
        dates = pd.bdate_range(start="2026-05-01", end="2026-10-30")
        base = 300.0 if ticker.startswith("^") else 200.0
        step = 0.25 if ticker.startswith("^") else 1.0
        values = [base + (i * step) for i in range(len(dates))]
        df = pd.DataFrame({
            "date": dates.date,
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "adj_close": values,
            "volume": [1_000_000 + i for i in range(len(dates))],
        })
        return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)


def test_pipeline_graceful_degradation_when_collector_fails(tmp_path):
    data_dir = tmp_path / "data"
    site_dir = tmp_path / "site"
    config_dir = tmp_path / "config"
    (data_dir / "canonical").mkdir(parents=True)
    (data_dir / "derived").mkdir(parents=True)
    (site_dir / "data").mkdir(parents=True)
    config_dir.mkdir(parents=True)

    cfg = PipelineConfig(
        data_dir=data_dir,
        site_dir=site_dir,
        config_dir=config_dir,
    )

    collectors: list[Collector] = [
        MockFailingCollector(),
        MockSuccessfulCollector(),
    ]

    report = run_pipeline(
        collectors=collectors,
        config=cfg,
        now=datetime(2026, 11, 2, 10, 0),
        skip_price_fetch=True,
    )

    assert report.success is True
    assert report.total_events_collected == 1
    assert "FAILING_COLLECTOR" in report.failed_sources
    assert "SUCCESS_COLLECTOR" in report.successful_sources

    events_json = site_dir / "data" / "events.json"
    assert events_json.exists()
    data = json.loads(events_json.read_text(encoding="utf-8"))
    assert len(data) >= 1
    assert data[0]["ticker"] == "005930"
    assert data[0]["d_day"] == (date(2026, 11, 20) - date(2026, 11, 2)).days

    meta_json = site_dir / "data" / "metadata.json"
    assert meta_json.exists()
    content = meta_json.read_text(encoding="utf-8")
    assert "secret" not in content.lower()
    assert "token" not in content.lower()
    assert "password" not in content.lower()


def test_pipeline_uses_configured_price_provider_for_real_backtest(tmp_path):
    data_dir = tmp_path / "data"
    site_dir = tmp_path / "site"
    config_dir = tmp_path / "config"
    (data_dir / "canonical").mkdir(parents=True)
    (data_dir / "derived").mkdir(parents=True)
    (site_dir / "data").mkdir(parents=True)
    config_dir.mkdir(parents=True)

    provider = DeterministicPriceProvider()
    cfg = PipelineConfig(
        data_dir=data_dir,
        site_dir=site_dir,
        config_dir=config_dir,
        price_provider=provider,
    )

    run_pipeline(
        collectors=[MockHistoricalCollector()],
        config=cfg,
        now=datetime(2026, 11, 2, 10, 0),
        skip_price_fetch=False,
    )

    assert any(call[0] == "005930" for call in provider.calls)
    assert any(call[0] == "^KS11" for call in provider.calls)

    returns_csv = data_dir / "derived" / "backtest_event_returns.csv"
    assert returns_csv.exists()
    returns_df = pd.read_csv(returns_csv)
    d0 = returns_df[returns_df["offset"] == 0].iloc[0]

    expected_stock = provider.history(
        "005930", date(2026, 9, 15), date(2026, 9, 15)
    ).iloc[0]["adj_close"]
    assert d0["price"] == pytest.approx(expected_stock)
    assert d0["return_from_d0"] == pytest.approx(0.0)


def test_pipeline_does_not_fetch_prices_for_legacy_hidden_dart_noise(tmp_path):
    data_dir = tmp_path / "data"
    site_dir = tmp_path / "site"
    config_dir = tmp_path / "config"
    (data_dir / "canonical").mkdir(parents=True)
    (data_dir / "derived").mkdir(parents=True)
    (site_dir / "data").mkdir(parents=True)
    config_dir.mkdir(parents=True)

    provider = DeterministicPriceProvider()
    cfg = PipelineConfig(
        data_dir=data_dir,
        site_dir=site_dir,
        config_dir=config_dir,
        price_provider=provider,
    )

    run_pipeline(
        collectors=[MockLegacyNoiseCollector()],
        config=cfg,
        now=datetime(2026, 11, 2, 10, 0),
        skip_price_fetch=False,
    )

    assert not any(call[0] == "123456" for call in provider.calls)


def test_skip_price_fetch_preserves_existing_backtest_and_refreshes_manual_relations(tmp_path):
    data_dir = tmp_path / "data"
    site_dir = tmp_path / "site"
    config_dir = tmp_path / "config"
    canonical_dir = data_dir / "canonical"
    derived_dir = data_dir / "derived"
    canonical_dir.mkdir(parents=True)
    derived_dir.mkdir(parents=True)
    (site_dir / "data").mkdir(parents=True)
    config_dir.mkdir(parents=True)

    returns_csv = derived_dir / "backtest_event_returns.csv"
    pd.DataFrame([
        {
            "event_id": "OLD_EVENT",
            "ticker": "005930",
            "relation_grade": "A",
            "event_session_date": "2026-10-01",
            "offset": 0,
            "price": 100.0,
            "return_from_d0": 0.0,
            "benchmark_return": 0.0,
            "abnormal_return": 0.0,
            "volume_ratio_20d": 1.0,
        }
    ]).to_csv(returns_csv, index=False)

    (canonical_dir / "manual_relations.csv").write_text(
        "relation_id,from_entity,to_ticker,relation_type,relation_grade,relation_score,relation_known_date,relation_start_date,relation_end_date,evidence_source,source_url,ingest_mode\n"
        "REL_HMG,현대차그룹,005380,PROJECT_INVESTOR,A,90,2026-10-30,2026-10-30,,공식 발표,https://example.com/source,MANUAL\n",
        encoding="utf-8",
    )

    cfg = PipelineConfig(data_dir=data_dir, site_dir=site_dir, config_dir=config_dir)
    run_pipeline(
        collectors=[MockFutureHyundaiCollector()],
        config=cfg,
        now=datetime(2026, 11, 3, 10, 0),
        skip_price_fetch=True,
    )

    preserved = pd.read_csv(returns_csv)
    assert len(preserved) == 1
    assert preserved.iloc[0]["event_id"] == "OLD_EVENT"

    details = json.loads((site_dir / "data" / "event_details.json").read_text(encoding="utf-8"))
    detail = next(value for value in details.values() if value["company"] == "현대차그룹")
    relation = next(row for row in detail["related_securities"] if row["ticker"] == "005380")
    assert relation["relation_grade"] == "A"
    assert relation["ingest_mode"] == "MANUAL"
