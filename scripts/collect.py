"""Main scheduled collection script for Event Radar."""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

# Add src to pythonpath
src_dir = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(src_dir))

from event_radar.pipeline import run_pipeline, PipelineConfig
from event_radar.collectors.dart import DartCollector
from event_radar.collectors.dart_five_pct import DartFivePctCollector
from event_radar.collectors.sec import SecCollector
from event_radar.collectors.news_future import DEFAULT_QUERIES, NewsFutureCollector
from event_radar.collectors.fda import FdaCollector
from event_radar.collectors.kind_ipo import KindIpoCollector
from event_radar.collectors.fomc import FomcCollector
from event_radar.collectors.entertainment import EntertainmentCollector
from event_radar.collectors.games import GamesCollector
from event_radar.collectors.index_changes import IndexChangesCollector
from event_radar.collectors.historical_seed import HistoricalSeedCollector


# Naver headlines frequently omit words like "예정" even when the article contains
# a clear future date. Broaden retrieval vocabulary while keeping the collector's
# strict future-date/catalyst/temporal-link filters unchanged.
EXTRA_NEWS_QUERIES = [
    "신작 출시",
    "신제품 출시",
    "내달 출시",
    "다음달 출시",
    "연내 출시",
    "내년 출시",
    "수주 계약",
    "내달 수주",
    "연내 수주",
    "내년 수주",
    "공급 계약",
    "내달 공급 계약",
    "연내 공급 계약",
    "내년 공급 계약",
    "연내 인수",
    "내달 인수",
    "내년 인수",
    "인수 합병",
    "경영권 분쟁",
    "임시주총",
    "주총 표대결",
    "임상 결과",
    "임상 발표",
    "내달 임상",
    "내년 임상",
    "원전 수주",
    "원전 입찰",
    "판결 선고",
]


def _news_collector() -> NewsFutureCollector:
    news_queries = list(dict.fromkeys([*DEFAULT_QUERIES, *EXTRA_NEWS_QUERIES]))
    return NewsFutureCollector(queries=news_queries)


def build_collectors(root: Path, fast_refresh: bool = False):
    """Build production collectors without test fixtures.

    Fast refresh only re-queries future news. Existing canonical events from
    regulators/calendars remain in the database and are re-exported, while
    manual relations are merged on every pipeline run.
    """
    if fast_refresh:
        return [_news_collector()]

    return [
        HistoricalSeedCollector(config_path=root / "config" / "historical_events.csv"),
        DartCollector(),
        DartFivePctCollector(),
        SecCollector(),
        _news_collector(),
        FdaCollector(config_path=root / "config" / "site_registry.yaml"),
        KindIpoCollector(),
        FomcCollector(history_start=date(2021, 1, 1)),
        EntertainmentCollector(config_path=root / "config" / "site_registry.yaml"),
        GamesCollector(config_path=root / "config" / "site_registry.yaml"),
        IndexChangesCollector(config_path=root / "config" / "site_registry.yaml"),
    ]


def prepare_fast_refresh_collectors(root: Path):
    """Capture Naver credentials in NEWS_FUTURE but keep DART for name resolution.

    The NewsFutureCollector stores Naver credentials on construction. Clearing
    only the Naver environment afterwards prevents IPO relation enrichment from
    performing a second news-search pass, while DART remains available so the
    listed-company registry can resolve company names into real stock tickers.
    """
    collectors = build_collectors(root, fast_refresh=True)
    for key in ("NAVER_API_HUB_KEY_ID", "NAVER_API_HUB_KEY"):
        os.environ.pop(key, None)
    return collectors


def main():
    parser = argparse.ArgumentParser(description="Collect and export Event Radar data")
    parser.add_argument(
        "--skip-price-fetch",
        action="store_true",
        help="Fast refresh: collect future news, merge relations, and preserve existing backtest returns.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    config = PipelineConfig(
        data_dir=root / "data",
        site_dir=root / "site",
        config_dir=root / "config",
        refresh_market_prices=not args.skip_price_fetch,
        refresh_public_registry=not args.skip_price_fetch,
    )

    collectors = (
        prepare_fast_refresh_collectors(root)
        if args.skip_price_fetch
        else build_collectors(root)
    )

    print("=== Starting Event Radar Collection Pipeline ===")
    report = run_pipeline(
        collectors=collectors,
        config=config,
        skip_price_fetch=args.skip_price_fetch,
    )

    print(f"Pipeline Completed in {report.duration_sec:.2f}s")
    print(
        "Phase timings: "
        f"collect={report.collection_duration_sec:.2f}s, "
        f"map={report.mapping_duration_sec:.2f}s, "
        f"backtest={report.backtest_duration_sec:.2f}s"
    )
    print(f"Total events collected: {report.total_events_collected}")
    print(f"Successful sources: {', '.join(report.successful_sources)}")
    if report.failed_sources:
        print(f"Failed sources (graceful): {', '.join(report.failed_sources)}")
    print(f"New revisions recorded: {report.new_revisions_count}")


if __name__ == "__main__":
    main()
