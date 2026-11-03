"""End-to-end event collection, normalization, backtesting, and export pipeline."""

from __future__ import annotations
import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
import time
from typing import Optional
import pandas as pd

from event_radar.models import Event, EventRevision, Relation, EventSecurity, RawEvent
from event_radar.normalize import normalize_event
from event_radar.dedupe import merge_events
from event_radar.relations import resolve_related_securities, load_relations_csv, save_relations_csv
from event_radar.theme import load_theme_mappings, merge_event_securities, resolve_theme_securities
from event_radar.entity_resolver import ListedCompanyRegistry
from event_radar.ipo_enrichment import IpoRelationEnricher
from event_radar.manual.google_sheet import load_manual_rows, apply_manual_overrides, apply_manual_relations
from event_radar.prices.base import PriceProvider, CachedPriceProvider
from event_radar.prices.yahoo import YahooPriceProvider
from event_radar.prices.calendar import get_trading_calendar
from event_radar.backtest.align import resolve_event_session
from event_radar.backtest.returns import calculate_event_window_returns
from event_radar.backtest.metrics import summarize_event_group, BacktestSummary
from event_radar.backtest.strategies import evaluate_strategies, StrategyResult
from event_radar.scoring import ScoreInput, ScoreResult, calculate_event_score
from event_radar.export import export_site_data
from event_radar.collectors.base import Collector


RETURN_COLUMNS = [
    "event_id", "ticker", "relation_grade", "event_session_date", "offset",
    "price", "return_from_d0", "benchmark_return", "abnormal_return",
    "volume_ratio_20d",
]

BENCHMARK_BY_COUNTRY = {
    "KR": "^KS11",
    "US": "^GSPC",
}


@dataclass
class PipelineConfig:
    data_dir: Path = Path("data")
    site_dir: Path = Path("site")
    config_dir: Path = Path("config")
    price_provider: Optional[PriceProvider] = None


@dataclass
class PipelineReport:
    success: bool
    total_events_collected: int
    successful_sources: list[str] = field(default_factory=list)
    failed_sources: list[str] = field(default_factory=list)
    new_revisions_count: int = 0
    duration_sec: float = 0.0


def load_canonical_events(path: Path) -> list[Event]:
    if not path.exists():
        return []
    events: list[Event] = []
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row or not row.get("event_id"):
                continue
            ann_raw = row["announced_at"].strip()
            ann = datetime.fromisoformat(ann_raw) if " " in ann_raw or "T" in ann_raw else datetime.combine(date.fromisoformat(ann_raw), datetime.min.time())
            f_seen = datetime.fromisoformat(row.get("first_seen_at", "").strip() or ann.isoformat())
            l_seen = datetime.fromisoformat(row.get("last_seen_at", "").strip() or datetime.now().isoformat())
            needs_rev = str(row.get("needs_review", "False")).strip().lower() in ("true", "1")
            event_date = date.fromisoformat(row["event_date"].strip()[:10])
            precision = row.get("date_precision", "").strip().upper() or "EXACT_DATE"
            window_start_raw = row.get("window_start", "").strip()
            window_end_raw = row.get("window_end", "").strip()
            window_start = date.fromisoformat(window_start_raw[:10]) if window_start_raw else event_date
            window_end = date.fromisoformat(window_end_raw[:10]) if window_end_raw else event_date

            events.append(
                Event(
                    event_id=row["event_id"].strip(),
                    country=row.get("country", "KR").strip().upper(),  # type: ignore
                    event_type=row.get("event_type", "OTHER").strip().upper(),
                    event_name=row.get("event_name", "").strip(),
                    primary_ticker=row.get("primary_ticker", "").strip().upper(),
                    primary_company=row.get("primary_company", "").strip(),
                    announced_at=ann,
                    event_date=event_date,
                    date_precision=precision,  # type: ignore
                    window_start=window_start,
                    window_end=window_end,
                    event_time_context=row.get("event_time_context", "DATE_ONLY").strip(),  # type: ignore
                    status=row.get("status", "CONFIRMED").strip().upper(),  # type: ignore
                    source_kind=row.get("source_kind", "REGULATOR").strip().upper(),  # type: ignore
                    source_name=row.get("source_name", "UNKNOWN").strip(),
                    source_url=row.get("source_url", "").strip(),
                    source_event_uid=row.get("source_event_uid", "").strip() or None,
                    evidence_text=row.get("evidence_text", "").strip(),
                    ingest_mode=row.get("ingest_mode", "AUTO").strip(),  # type: ignore
                    first_seen_at=f_seen,
                    last_seen_at=l_seen,
                    needs_review=needs_rev,
                )
            )
    return events


def save_canonical_events(events: list[Event], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "event_id", "country", "event_type", "event_name", "primary_ticker", "primary_company",
        "announced_at", "event_date", "date_precision", "window_start", "window_end",
        "event_time_context", "status", "source_kind", "source_name",
        "source_url", "source_event_uid", "evidence_text", "ingest_mode", "first_seen_at",
        "last_seen_at", "needs_review",
    ]
    with open(path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ev in events:
            window_start = ev.window_start or ev.event_date
            window_end = ev.window_end or ev.event_date
            writer.writerow({
                "event_id": ev.event_id,
                "country": ev.country,
                "event_type": ev.event_type,
                "event_name": ev.event_name,
                "primary_ticker": ev.primary_ticker,
                "primary_company": ev.primary_company,
                "announced_at": ev.announced_at.isoformat(),
                "event_date": ev.event_date.isoformat(),
                "date_precision": ev.date_precision,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "event_time_context": ev.event_time_context,
                "status": ev.status,
                "source_kind": ev.source_kind,
                "source_name": ev.source_name,
                "source_url": ev.source_url,
                "source_event_uid": ev.source_event_uid or "",
                "evidence_text": ev.evidence_text,
                "ingest_mode": ev.ingest_mode,
                "first_seen_at": ev.first_seen_at.isoformat(),
                "last_seen_at": ev.last_seen_at.isoformat(),
                "needs_review": ev.needs_review,
            })


def load_canonical_revisions(path: Path) -> list[EventRevision]:
    if not path.exists():
        return []
    revisions: list[EventRevision] = []
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row or not row.get("event_id"):
                continue
            revisions.append(
                EventRevision(
                    event_id=row["event_id"].strip(),
                    revision_no=int(row.get("revision_no", 1)),
                    changed_at=datetime.fromisoformat(row["changed_at"].strip()),
                    field_name=row["field_name"].strip(),
                    old_value=row.get("old_value", ""),
                    new_value=row.get("new_value", ""),
                    source_url=row.get("source_url", ""),
                    change_reason=row.get("change_reason", ""),
                )
            )
    return revisions


def save_canonical_revisions(revisions: list[EventRevision], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["event_id", "revision_no", "changed_at", "field_name", "old_value", "new_value", "source_url", "change_reason"]
    with open(path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in revisions:
            writer.writerow({
                "event_id": r.event_id,
                "revision_no": r.revision_no,
                "changed_at": r.changed_at.isoformat(),
                "field_name": r.field_name,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "source_url": r.source_url,
                "change_reason": r.change_reason,
            })


def _resolve_price_provider(config: PipelineConfig) -> PriceProvider:
    """Return the explicitly configured provider or the cached Yahoo adapter."""
    if config.price_provider is not None:
        return config.price_provider
    return CachedPriceProvider(
        YahooPriceProvider(),
        cache_dir=config.data_dir / "cache" / "prices",
    )


def resolve_event_stock_rows(
    event: Event,
    relations: list[Relation],
    theme_mappings: list,
    registry: ListedCompanyRegistry,
    ipo_enricher: IpoRelationEnricher,
    as_of: datetime,
) -> list[EventSecurity]:
    """Compose all stock-resolution layers for one event.

    Strongest evidence wins per ticker: A direct mentions/economic relations,
    evidence-backed B relations, THEME candidates, then informational PROXY rows.
    """
    rows = resolve_related_securities(event, relations)
    rows = merge_event_securities(rows, registry.resolve_mentions(event))
    rows = merge_event_securities(rows, ipo_enricher.enrich(event, registry, as_of=as_of))
    rows = merge_event_securities(rows, resolve_theme_securities(event, theme_mappings))
    return rows


def run_pipeline(
    collectors: list[Collector],
    config: PipelineConfig,
    now: Optional[datetime] = None,
    skip_price_fetch: bool = False,
) -> PipelineReport:
    """Execute end-to-end collection, merge, analysis, and site export."""
    start_time = time.time()
    if now is None:
        now = datetime.now()

    canonical_dir = config.data_dir / "canonical"
    derived_dir = config.data_dir / "derived"
    site_data_dir = config.site_dir / "data"

    canonical_dir.mkdir(parents=True, exist_ok=True)
    derived_dir.mkdir(parents=True, exist_ok=True)
    site_data_dir.mkdir(parents=True, exist_ok=True)

    events_csv = canonical_dir / "events.csv"
    revisions_csv = canonical_dir / "event_revisions.csv"
    relations_csv = canonical_dir / "relations.csv"
    manual_events_csv = canonical_dir / "manual_events.csv"
    manual_relations_csv = canonical_dir / "manual_relations.csv"
    theme_mappings_csv = config.config_dir / "theme_mappings.csv"

    # 1. Load existing canonical data and reusable entity resolution sources.
    existing_events = load_canonical_events(events_csv)
    existing_revisions = load_canonical_revisions(revisions_csv)
    existing_relations = load_relations_csv(relations_csv)
    theme_mappings = load_theme_mappings(theme_mappings_csv)
    registry = ListedCompanyRegistry.load_korean(
        cache_path=config.data_dir / "cache" / "listed_companies_kr.csv"
    )
    ipo_enricher = IpoRelationEnricher()

    # 2. Run collectors with graceful degradation
    successful_sources: list[str] = []
    failed_sources: list[str] = []
    incoming_raw: list[RawEvent] = []
    since = now - timedelta(days=7)

    collector_status = {}
    for col in collectors:
        try:
            col_events = col.collect(since=since)
            incoming_raw.extend(col_events)
            successful_sources.append(col.source_name)
            collector_status[col.source_name] = "SUCCESS"
        except Exception:
            failed_sources.append(col.source_name)
            collector_status[col.source_name] = "FAILED"

    # 3. Normalize raw events
    incoming_events = [normalize_event(r, now=now) for r in incoming_raw]

    # 4. Merge incoming auto events with existing
    merge_res = merge_events(
        existing=existing_events,
        incoming=incoming_events,
        existing_revisions=existing_revisions,
        now=now,
    )
    current_events = merge_res.events
    all_revisions = list(existing_revisions) + merge_res.new_revisions

    # 5. Apply manual overrides
    manual_input = load_manual_rows(manual_events_csv, manual_relations_csv)
    if manual_input.events:
        manual_res = apply_manual_overrides(
            auto_events=current_events,
            manual_events=manual_input.events,
            revisions=all_revisions,
            now=now,
        )
        current_events = manual_res.events
        all_revisions.extend(manual_res.new_revisions)

    all_relations = apply_manual_relations(existing_relations, manual_input.relations)

    # 6. Save updated canonical data
    save_canonical_events(current_events, events_csv)
    save_canonical_revisions(all_revisions, revisions_csv)
    save_relations_csv(all_relations, relations_csv)

    # 7. Resolve direct/economic, text-mentioned, IPO, and theme securities.
    event_securities: dict[str, list[EventSecurity]] = {}
    all_mapped_rows = []
    for ev in current_events:
        secs = resolve_event_stock_rows(
            ev,
            relations=all_relations,
            theme_mappings=theme_mappings,
            registry=registry,
            ipo_enricher=ipo_enricher,
            as_of=now,
        )
        event_securities[ev.event_id] = secs
        for s in secs:
            all_mapped_rows.append({
                "event_id": ev.event_id,
                "ticker": s.ticker,
                "relation_grade": s.relation_grade,
                "relation_score": s.relation_score,
                "relation_type": s.relation_type,
                "evidence_text": s.evidence_text,
            })

    # Always refresh the map so stale rows cannot survive an empty run.
    pd.DataFrame(all_mapped_rows, columns=[
        "event_id", "ticker", "relation_grade", "relation_score",
        "relation_type", "evidence_text",
    ]).to_csv(derived_dir / "event_security_map.csv", index=False)

    # 8. Real-price backtest, Strategy, and Scoring
    event_scores: dict[str, ScoreResult] = {}
    strategy_results: dict[str, list[StrategyResult]] = {}
    backtest_summaries: dict[str, BacktestSummary] = {}

    if current_events:
        calendar_start = min(ev.event_date for ev in current_events) - timedelta(days=10)
    else:
        calendar_start = now.date() - timedelta(days=180)
    calendar_end = now.date() + timedelta(days=90)
    calendar_kr = get_trading_calendar("KR", calendar_start, calendar_end)
    calendar_us = get_trading_calendar("US", calendar_start, calendar_end)

    return_frames: list[pd.DataFrame] = []
    price_provider = None if skip_price_fetch else _resolve_price_provider(config)

    for ev in current_events:
        trading_days = calendar_us if ev.country == "US" else calendar_kr
        session_date, _ = resolve_event_session(ev.event_date, ev.event_time_context, trading_days)

        # Future events do not have realized D0/D+ returns yet. Never synthesize them.
        if price_provider is None or session_date > now.date():
            continue

        benchmark_ticker = BENCHMARK_BY_COUNTRY.get(ev.country, "^GSPC")
        start_date = session_date - timedelta(days=120)
        end_date = min(now.date(), session_date + timedelta(days=45))

        for sec in event_securities.get(ev.event_id, []):
            if not sec.ticker:
                continue
            try:
                stock_prices = price_provider.history(sec.ticker, start_date, end_date)
                benchmark_prices = price_provider.history(benchmark_ticker, start_date, end_date)
                frame = calculate_event_window_returns(
                    event_id=ev.event_id,
                    ticker=sec.ticker,
                    relation_grade=sec.relation_grade,
                    event_session_date=session_date,
                    stock_prices=stock_prices,
                    benchmark_prices=benchmark_prices,
                )
                if not frame.empty:
                    return_frames.append(frame)
            except Exception:
                # A price-provider failure for one security must not stop collection/export.
                continue

    if return_frames:
        all_returns_df = pd.concat(return_frames, ignore_index=True)
    else:
        all_returns_df = pd.DataFrame(columns=RETURN_COLUMNS)
    all_returns_df.to_csv(derived_dir / "backtest_event_returns.csv", index=False)

    for ev in current_events:
        ev_df = all_returns_df[all_returns_df["event_id"] == ev.event_id]
        primary_sec = event_securities.get(ev.event_id, [None])[0]
        rel_score = primary_sec.relation_score if primary_sec else 0
        primary_grade = primary_sec.relation_grade if primary_sec else "UNMAPPED"

        # D+5 is a realized post-event outcome; unlike D0 it is not identically zero.
        b_sum = summarize_event_group(ev_df, target_offset=5)
        backtest_summaries[ev.event_id] = b_sum

        strats = evaluate_strategies(
            ev_df,
            event_type=ev.event_type,
            relation_grade=primary_grade,
        )
        strategy_results[ev.event_id] = strats
        sampled_strats = [s for s in strats if s.sample_n > 0]
        robustness = (
            sum(s.robustness_score for s in sampled_strats) / len(sampled_strats)
            if sampled_strats else 0.5
        )

        event_scores[ev.event_id] = calculate_event_score(
            ScoreInput(
                status=ev.status,
                relation_score=rel_score,
                sample_n=b_sum.sample_n,
                median_abnormal_return=b_sum.median_abnormal_return,
                win_rate=b_sum.win_rate,
                robustness_score=robustness,
            )
        )

    # 9. Export Site Data
    export_site_data(
        events=current_events,
        revisions=all_revisions,
        event_securities=event_securities,
        event_scores=event_scores,
        event_returns_df=all_returns_df,
        strategy_results=strategy_results,
        backtest_summaries=backtest_summaries,
        output_dir=site_data_dir,
        collector_status=collector_status,
        now=now,
    )

    duration = time.time() - start_time
    return PipelineReport(
        success=True,
        total_events_collected=len(incoming_events),
        successful_sources=successful_sources,
        failed_sources=failed_sources,
        new_revisions_count=len(merge_res.new_revisions),
        duration_sec=duration,
    )
