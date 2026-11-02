"""Export canonical data to public JSON contracts for GitHub Pages."""

from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from event_radar.models import Event, EventRevision, EventSecurity
from event_radar.scoring import ScoreResult
from event_radar.backtest.strategies import StrategyResult
from event_radar.backtest.metrics import BacktestSummary


def export_site_data(
    events: list[Event],
    revisions: list[EventRevision],
    event_securities: dict[str, list[EventSecurity]],
    event_scores: dict[str, ScoreResult],
    event_returns_df: Any,  # pd.DataFrame
    strategy_results: dict[str, list[StrategyResult]],
    backtest_summaries: dict[str, BacktestSummary],
    output_dir: Path | str = "site/data",
    collector_status: dict[str, str] | None = None,
    now: datetime | None = None,
) -> None:
    """Generate public JSON files for static GitHub Pages dashboard without any sensitive data."""
    if now is None:
        now = datetime.now()
    today = now.date()

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 1. site/data/events.json
    events_list = []
    for ev in events:
        d_day = (ev.event_date - today).days
        score = event_scores.get(ev.event_id)
        total_score = score.total_score if score else 50

        # Get primary relation score/grade
        sec_list = event_securities.get(ev.event_id, [])
        primary_rel = sec_list[0] if sec_list else None
        rel_grade = primary_rel.relation_grade if primary_rel else "A"
        rel_score = primary_rel.relation_score if primary_rel else 100

        events_list.append({
            "event_id": ev.event_id,
            "d_day": d_day,
            "country": ev.country,
            "ticker": ev.primary_ticker,
            "company": ev.primary_company,
            "event_type": ev.event_type,
            "event_name": ev.event_name,
            "event_date": ev.event_date.isoformat(),
            "relation_grade": rel_grade,
            "relation_score": rel_score,
            "event_score": total_score,
            "status": ev.status,
            "source_name": ev.source_name,
            "source_url": ev.source_url,
        })

    # Sort primarily by d_day ascending (closest upcoming first) or event_score descending
    events_list.sort(key=lambda x: (x["d_day"] < 0, abs(x["d_day"])))

    (out_path / "events.json").write_text(
        json.dumps(events_list, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 2. site/data/event_details.json
    details_map = {}
    for ev in events:
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

        ev_secs = [
            {
                "ticker": s.ticker,
                "relation_grade": s.relation_grade,
                "relation_score": s.relation_score,
                "relation_type": s.relation_type,
                "evidence_text": s.evidence_text,
            }
            for s in event_securities.get(ev_id, [])
        ]

        b_summary = backtest_summaries.get(ev_id, BacktestSummary())
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
            for s in strategy_results.get(ev_id, [])
        ]

        # Calculate event curve points from returns df if available
        curve_points = []
        if event_returns_df is not None and not getattr(event_returns_df, "empty", True):
            ev_rets = event_returns_df[event_returns_df["event_id"] == ev_id]
            if not ev_rets.empty:
                grouped = ev_rets.groupby("offset")[["return_from_d0", "abnormal_return"]].mean().reset_index()
                for _, r in grouped.iterrows():
                    curve_points.append({
                        "offset": int(r["offset"]),
                        "return_from_d0": round(float(r["return_from_d0"]), 4),
                        "abnormal_return": round(float(r["abnormal_return"]), 4),
                    })

        score_obj = event_scores.get(ev_id)
        score_breakdown = {
            "total": score_obj.total_score if score_obj else 50,
            "schedule": score_obj.schedule_points if score_obj else 20,
            "relation": score_obj.relation_points if score_obj else 20,
            "edge": score_obj.edge_points if score_obj else 5,
            "robustness": score_obj.robustness_points if score_obj else 5,
            "setup": score_obj.setup_points if score_obj else 0,
        }

        details_map[ev_id] = {
            "event_id": ev_id,
            "country": ev.country,
            "ticker": ev.primary_ticker,
            "company": ev.primary_company,
            "event_type": ev.event_type,
            "event_name": ev.event_name,
            "announced_at": ev.announced_at.isoformat(),
            "event_date": ev.event_date.isoformat(),
            "event_time_context": ev.event_time_context,
            "status": ev.status,
            "source_name": ev.source_name,
            "source_url": ev.source_url,
            "evidence_text": ev.evidence_text,
            "score_breakdown": score_breakdown,
            "revisions": ev_revs,
            "related_securities": ev_secs,
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

    # 3. site/data/metadata.json
    metadata = {
        "generated_at": now.isoformat(),
        "total_events": len(events),
        "kr_events": sum(1 for e in events if e.country == "KR"),
        "us_events": sum(1 for e in events if e.country == "US"),
        "version": "1.0.0",
        "collector_status": collector_status or {},
    }

    (out_path / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
