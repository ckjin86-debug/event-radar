"""Export canonical data to public JSON contracts for GitHub Pages."""

from __future__ import annotations
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from event_radar.models import Event, EventRevision, EventSecurity
from event_radar.scoring import ScoreInput, ScoreResult, calculate_event_score
from event_radar.backtest.strategies import StrategyResult, evaluate_strategies
from event_radar.backtest.metrics import BacktestSummary, summarize_event_group
from event_radar.backtest.historical import build_historical_peer_frame


PUBLIC_NEWS_RELATION_GRADES = {"A", "B", "THEME"}
EVENT_FIRST_PUBLIC_TYPES = {"CONTROL_DISPUTE", "ELECTION", "TENDER", "POLICY"}
EVENT_FIRST_KEYWORDS_BY_TYPE = {
    "CONTROL_DISPUTE": ("경영권", "임시주총", "표대결", "공개매수"),
    "ELECTION": ("대선", "총선", "지방선거", "경선", "선거"),
    "TENDER": ("원전", "원자력", "smr", "방산", "국방", "전투기", "함정", "잠수함", "미사일"),
    "POLICY": ("반도체", "배터리", "원전", "원자력", "관세", "보조금", "수출규제", "세제", "전기차"),
}
GENERIC_EVENT_ENTITIES = {
    "",
    "cm",
    "경기도",
    "서울시",
    "정부",
    "원료",
    "시장",
    "업계",
    "국내",
    "관계자",
    "koreamarket",
}


def _is_actual_convertible_listing(ev: Event) -> bool:
    """Return True only when a legacy DART convertible row reflects new-share listing."""
    combined = f"{ev.event_name} {ev.evidence_text}".replace(" ", "")
    has_exercise = any(
        keyword in combined
        for keyword in ("전환청구권행사", "전환권행사", "신주인수권행사")
    )
    has_listing = "신주상장" in combined or "상장예정" in combined
    return has_exercise and has_listing


def _is_visible_radar_event(ev: Event) -> bool:
    """Hide historical rows that no longer meet the radar's signal policy."""
    if ev.source_name == "DART" and ev.event_type == "RIGHTS_ISSUE":
        return False
    if ev.source_name == "KIND_IPO" and ev.event_type != "IPO_LISTING":
        return False
    if (
        ev.source_name == "DART"
        and ev.event_type == "CONVERTIBLE_LISTING"
        and not _is_actual_convertible_listing(ev)
    ):
        return False
    return True


def _public_relation_rows(securities: list[EventSecurity]) -> list[EventSecurity]:
    return [
        row
        for row in securities
        if row.ticker and row.relation_grade in PUBLIC_NEWS_RELATION_GRADES
    ]


def _news_window_is_publicly_actionable(ev: Event, today: date) -> bool:
    """Require a genuinely future window instead of a vague current-period mention."""
    window_start = ev.window_start or ev.event_date
    window_end = ev.window_end or ev.event_date
    if window_end < today:
        return False
    if ev.date_precision == "EXACT_DATE":
        return ev.event_date >= today
    if ev.date_precision == "WEEK":
        return window_end >= today
    if ev.date_precision in {"MONTH", "QUARTER", "HALF_YEAR", "YEAR"}:
        return window_start > today
    return ev.event_date >= today


def _event_first_entity_is_plausible(ev: Event) -> bool:
    company_key = re.sub(r"[^0-9A-Za-z가-힣]", "", ev.primary_company or "").lower()
    if company_key in GENERIC_EVENT_ENTITIES or len(company_key) < 3 or len(company_key) > 40:
        return False
    keywords = EVENT_FIRST_KEYWORDS_BY_TYPE.get(ev.event_type, ())
    if not keywords:
        return False
    combined = f"{ev.event_name} {ev.evidence_text}".lower()
    return any(keyword.lower() in combined for keyword in keywords)


def _is_public_news_event(
    ev: Event,
    securities: list[EventSecurity],
    today: date,
) -> bool:
    if ev.source_name != "NEWS_FUTURE":
        return True
    if not _news_window_is_publicly_actionable(ev, today):
        return False
    if _public_relation_rows(securities):
        return True
    return ev.event_type in EVENT_FIRST_PUBLIC_TYPES and _event_first_entity_is_plausible(ev)


def _news_dedupe_key(ev: Event, securities: list[EventSecurity]) -> tuple[str, str, str, str]:
    mapped = sorted({row.ticker for row in _public_relation_rows(securities)})
    if mapped:
        anchor = ",".join(mapped)
    else:
        anchor = re.sub(r"[^0-9A-Za-z가-힣]", "", ev.primary_company or "").lower()
    window_start = (ev.window_start or ev.event_date).isoformat()
    window_end = (ev.window_end or ev.event_date).isoformat()
    return anchor, ev.event_type, window_start, window_end


def _news_preference(ev: Event, securities: list[EventSecurity]) -> tuple[int, int, int, float]:
    grade_rank = {"A": 4, "B": 3, "THEME": 2}
    relation_rank = max((grade_rank.get(row.relation_grade, 0) for row in securities), default=0)
    manual_rank = 1 if any(row.ingest_mode in {"MANUAL", "AUTO+MANUAL"} for row in securities) else 0
    precision_rank = {
        "EXACT_DATE": 5,
        "WEEK": 4,
        "MONTH": 3,
        "QUARTER": 2,
        "HALF_YEAR": 1,
        "YEAR": 0,
    }.get(ev.date_precision, 0)
    return relation_rank, manual_rank, precision_rank, ev.announced_at.timestamp()


def _select_public_visible_events(
    events: list[Event],
    event_securities: dict[str, list[EventSecurity]],
    today: date,
) -> list[Event]:
    """Keep non-news events and semantically select/dedupe public future-news rows."""
    non_news = [ev for ev in events if ev.source_name not in {"NEWS_FUTURE", "HISTORICAL_SEED"}]
    news_by_key: dict[tuple[str, str, str, str], Event] = {}

    for ev in events:
        if ev.source_name != "NEWS_FUTURE":
            continue
        securities = event_securities.get(ev.event_id, [])
        if not _is_public_news_event(ev, securities, today):
            continue
        key = _news_dedupe_key(ev, securities)
        current = news_by_key.get(key)
        if current is None:
            news_by_key[key] = ev
            continue
        if _news_preference(ev, securities) > _news_preference(
            current,
            event_securities.get(current.event_id, []),
        ):
            news_by_key[key] = ev

    return non_news + list(news_by_key.values())


def _serialize_securities(securities: list[EventSecurity]) -> list[dict[str, Any]]:
    return [
        {
            "ticker": s.ticker,
            "relation_grade": s.relation_grade,
            "relation_score": s.relation_score,
            "relation_type": s.relation_type,
            "evidence_text": s.evidence_text,
            "evidence_source": s.evidence_source,
            "source_url": s.source_url,
            "relation_known_date": s.relation_known_date.isoformat() if s.relation_known_date else "",
            "ingest_mode": s.ingest_mode,
            "from_entity": s.from_entity,
        }
        for s in securities
    ]


def _analyze_historical_peers(
    event: Event,
    analysis_events: list[Event],
    event_securities: dict[str, list[EventSecurity]],
    event_returns_df: Any,
) -> tuple[Any, BacktestSummary, list[StrategyResult], ScoreResult]:
    """Build one no-lookahead historical study and its score for an event."""
    securities = event_securities.get(event.event_id, [])
    primary = securities[0] if securities else None
    relation_grade = primary.relation_grade if primary else "UNMAPPED"
    relation_score = primary.relation_score if primary else 0

    if event_returns_df is not None and not getattr(event_returns_df, "empty", True):
        peer_df = build_historical_peer_frame(
            events=analysis_events,
            returns_df=event_returns_df,
            target_event=event,
            relation_grade=relation_grade,
        )
        summary = summarize_event_group(peer_df, target_offset=5)
        strategies = evaluate_strategies(
            peer_df,
            event_type=event.event_type,
            relation_grade=relation_grade,
        )
    else:
        peer_df = None
        summary = BacktestSummary()
        strategies = []

    sampled = [strategy for strategy in strategies if strategy.sample_n > 0]
    robustness = (
        sum(strategy.robustness_score for strategy in sampled) / len(sampled)
        if sampled else 0.5
    )
    score = calculate_event_score(
        ScoreInput(
            status=event.status,
            relation_score=relation_score,
            sample_n=summary.sample_n,
            median_abnormal_return=summary.median_abnormal_return,
            win_rate=summary.win_rate,
            robustness_score=robustness,
        )
    )
    return peer_df, summary, strategies, score


def export_site_data(
    events: list[Event],
    revisions: list[EventRevision],
    event_securities: dict[str, list[EventSecurity]],
    event_scores: dict[str, ScoreResult],
    event_returns_df: Any,
    strategy_results: dict[str, list[StrategyResult]],
    backtest_summaries: dict[str, BacktestSummary],
    output_dir: Path | str = "site/data",
    collector_status: dict[str, str] | None = None,
    now: datetime | None = None,
) -> None:
    """Generate public JSON files for static GitHub Pages."""
    if now is None:
        now = datetime.now()
    today = now.date()

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    analysis_events = [ev for ev in events if _is_visible_radar_event(ev)]
    historical_seed_events = [ev for ev in analysis_events if ev.source_name == "HISTORICAL_SEED"]
    visible_events = _select_public_visible_events(analysis_events, event_securities, today)
    historical_analysis = {
        ev.event_id: _analyze_historical_peers(
            event=ev,
            analysis_events=analysis_events,
            event_securities=event_securities,
            event_returns_df=event_returns_df,
        )
        for ev in visible_events
    }

    events_list = []
    for ev in visible_events:
        d_day = (ev.event_date - today).days
        _, _, _, score = historical_analysis[ev.event_id]

        sec_list = event_securities.get(ev.event_id, [])
        primary_rel = sec_list[0] if sec_list else None
        rel_grade = primary_rel.relation_grade if primary_rel else "UNMAPPED"
        rel_score = primary_rel.relation_score if primary_rel else 0
        rel_type = primary_rel.relation_type if primary_rel else "UNMAPPED"
        rel_ingest_mode = primary_rel.ingest_mode if primary_rel else "AUTO"
        window_start = ev.window_start or ev.event_date
        window_end = ev.window_end or ev.event_date

        events_list.append({
            "event_id": ev.event_id,
            "d_day": d_day,
            "country": ev.country,
            "ticker": ev.primary_ticker,
            "company": ev.primary_company,
            "event_type": ev.event_type,
            "event_name": ev.event_name,
            "event_date": ev.event_date.isoformat(),
            "date_precision": ev.date_precision,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "relation_grade": rel_grade,
            "relation_score": rel_score,
            "relation_type": rel_type,
            "relation_ingest_mode": rel_ingest_mode,
            "event_score": score.total_score,
            "status": ev.status,
            "source_name": ev.source_name,
            "source_url": ev.source_url,
        })

    events_list.sort(key=lambda x: (x["d_day"] < 0, abs(x["d_day"])))
    (out_path / "events.json").write_text(
        json.dumps(events_list, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    historical_library = [
        {
            "event_id": ev.event_id,
            "country": ev.country,
            "event_type": ev.event_type,
            "event_name": ev.event_name,
            "event_date": ev.event_date.isoformat(),
            "company": ev.primary_company,
            "source_url": ev.source_url,
            "evidence_text": ev.evidence_text,
            "related_securities": _serialize_securities(event_securities.get(ev.event_id, [])),
        }
        for ev in sorted(historical_seed_events, key=lambda item: item.event_date, reverse=True)
    ]
    (out_path / "historical_events.json").write_text(
        json.dumps(historical_library, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    event_lookup = {ev.event_id: ev for ev in analysis_events}
    details_map = {}
    for ev in visible_events:
        ev_id = ev.event_id
        ev_revs = [
            {
                "revision_no": r.revision_no,
                "changed_at": r.changed_at.isoformat(),
                "field_name": r.field_name,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "change_reason": r.change_reason,
            }
            for r in revisions if r.event_id == ev_id
        ]
        ev_revs.sort(key=lambda x: x["revision_no"])

        ev_secs = _serialize_securities(event_securities.get(ev_id, []))
        peer_df, b_summary, peer_strategies, score_obj = historical_analysis[ev_id]

        peer_ids: list[str] = []
        historical_peers: list[dict[str, Any]] = []
        if peer_df is not None and not peer_df.empty:
            peer_ids = sorted(
                {str(peer_id) for peer_id in peer_df["event_id"].dropna().unique()},
                key=lambda peer_id: event_lookup[peer_id].event_date if peer_id in event_lookup else date.min,
            )
            for peer_id in peer_ids:
                peer_event = event_lookup.get(peer_id)
                if peer_event is None:
                    continue
                peer_rows = peer_df[peer_df["event_id"] == peer_id]
                historical_peers.append({
                    "event_id": peer_id,
                    "country": peer_event.country,
                    "event_type": peer_event.event_type,
                    "event_name": peer_event.event_name,
                    "event_date": peer_event.event_date.isoformat(),
                    "company": peer_event.primary_company,
                    "source_name": peer_event.source_name,
                    "source_url": peer_event.source_url,
                    "evidence_text": peer_event.evidence_text,
                    "min_offset": int(peer_rows["offset"].min()),
                    "max_offset": int(peer_rows["offset"].max()),
                    "related_securities": _serialize_securities(event_securities.get(peer_id, [])),
                })

        strats = [
            {
                "name": f"D{s.entry_offset} -> D{s.exit_offset:+d}" if s.exit_offset != 0 else f"D{s.entry_offset} -> D0",
                "entry_offset": s.entry_offset,
                "exit_offset": s.exit_offset,
                "sample_n": s.sample_n,
                "mean_return": s.mean_return,
                "median_return": s.median_return,
                "win_rate": s.win_rate,
                "mean_abnormal_return": s.mean_abnormal_return,
                "median_abnormal_return": s.median_abnormal_return,
                "max_drawdown": s.max_drawdown,
                "robustness_score": s.robustness_score,
            }
            for s in peer_strategies
        ]

        curve_points = []
        if peer_df is not None and not peer_df.empty:
            grouped = peer_df.groupby("offset")[["return_from_d0", "abnormal_return"]].mean().reset_index()
            for _, r in grouped.iterrows():
                curve_points.append({
                    "offset": int(r["offset"]),
                    "return_from_d0": round(float(r["return_from_d0"]), 4),
                    "abnormal_return": round(float(r["abnormal_return"]), 4),
                })

        score_breakdown = {
            "total": score_obj.total_score,
            "schedule": score_obj.schedule_points,
            "relation": score_obj.relation_points,
            "edge": score_obj.edge_points,
            "robustness": score_obj.robustness_points,
            "setup": score_obj.setup_points,
        }
        window_start = ev.window_start or ev.event_date
        window_end = ev.window_end or ev.event_date

        details_map[ev_id] = {
            "event_id": ev_id,
            "country": ev.country,
            "ticker": ev.primary_ticker,
            "company": ev.primary_company,
            "event_type": ev.event_type,
            "event_name": ev.event_name,
            "announced_at": ev.announced_at.isoformat(),
            "event_date": ev.event_date.isoformat(),
            "date_precision": ev.date_precision,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "event_time_context": ev.event_time_context,
            "status": ev.status,
            "source_name": ev.source_name,
            "source_url": ev.source_url,
            "evidence_text": ev.evidence_text,
            "score_breakdown": score_breakdown,
            "revisions": ev_revs,
            "related_securities": ev_secs,
            "backtest_basis": "HISTORICAL_PEERS",
            "peer_sample_n": len(historical_peers),
            "d5_sample_n": b_summary.sample_n,
            "historical_peers": historical_peers,
            "backtest_summary": {
                "sample_n": b_summary.sample_n,
                "mean_return": b_summary.mean_return,
                "median_return": b_summary.median_return,
                "win_rate": b_summary.win_rate,
                "mean_abnormal_return": b_summary.mean_abnormal_return,
                "median_abnormal_return": b_summary.median_abnormal_return,
                "max_drawdown": b_summary.max_drawdown,
            },
            "strategy_summary": strats,
            "event_curve": curve_points,
            "sample_count": b_summary.sample_n,
            "latest_update": now.isoformat(),
        }

    (out_path / "event_details.json").write_text(
        json.dumps(details_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    news_candidates = sum(1 for ev in analysis_events if ev.source_name == "NEWS_FUTURE")
    news_visible = sum(1 for ev in visible_events if ev.source_name == "NEWS_FUTURE")
    metadata = {
        "generated_at": now.isoformat(),
        "total_events": len(visible_events),
        "kr_events": sum(1 for e in visible_events if e.country == "KR"),
        "us_events": sum(1 for e in visible_events if e.country == "US"),
        "historical_seed_events": len(historical_seed_events),
        "news_candidates": news_candidates,
        "news_visible": news_visible,
        "version": "1.0.0",
        "collector_status": collector_status or {},
    }

    (out_path / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )