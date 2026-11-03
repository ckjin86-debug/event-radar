"""Evidence-backed theme mapping for events whose listed securities are not explicit.

Theme mappings are intentionally separate from canonical A/B economic relations.
Political-theme rows stay THEME grade and can be time-bounded so stale narratives do
not get promoted into current direct relationships.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from event_radar.models import Event, EventSecurity, RelationGrade


@dataclass(frozen=True)
class ThemeMapping:
    mapping_id: str
    event_pattern: str
    ticker: str
    company: str
    relation_grade: RelationGrade
    relation_score: int
    relation_type: str
    valid_from: date | None = None
    valid_to: date | None = None
    evidence_text: str = ""
    source_url: str = ""


def _parse_optional_date(value: str | None) -> date | None:
    value = (value or "").strip()
    return date.fromisoformat(value[:10]) if value else None


def load_theme_mappings(path: Path | str) -> list[ThemeMapping]:
    path = Path(path)
    if not path.exists():
        return []

    rows: list[ThemeMapping] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row or not row.get("mapping_id") or not row.get("ticker"):
                continue
            grade = (row.get("relation_grade") or "THEME").strip().upper()
            if grade not in {"A", "B", "THEME"}:
                grade = "THEME"
            rows.append(
                ThemeMapping(
                    mapping_id=row["mapping_id"].strip(),
                    event_pattern=(row.get("event_pattern") or "").strip(),
                    ticker=row["ticker"].strip().upper(),
                    company=(row.get("company") or "").strip(),
                    relation_grade=grade,  # type: ignore[arg-type]
                    relation_score=max(0, min(100, int(row.get("relation_score") or 40))),
                    relation_type=(row.get("relation_type") or "MARKET_THEME").strip(),
                    valid_from=_parse_optional_date(row.get("valid_from")),
                    valid_to=_parse_optional_date(row.get("valid_to")),
                    evidence_text=(row.get("evidence_text") or "").strip(),
                    source_url=(row.get("source_url") or "").strip(),
                )
            )
    return rows


def _matches_event(mapping: ThemeMapping, event: Event) -> bool:
    if mapping.valid_from and event.event_date < mapping.valid_from:
        return False
    if mapping.valid_to and event.event_date > mapping.valid_to:
        return False
    if not mapping.event_pattern:
        return False

    haystack = " ".join(
        part
        for part in (
            event.event_name,
            event.primary_company,
            event.evidence_text,
        )
        if part
    )
    try:
        return re.search(mapping.event_pattern, haystack, re.IGNORECASE) is not None
    except re.error:
        return mapping.event_pattern.lower() in haystack.lower()


def resolve_theme_securities(event: Event, mappings: list[ThemeMapping]) -> list[EventSecurity]:
    """Resolve evidence-backed B/THEME candidates for an event.

    If multiple mapping rules point to the same ticker, keep the strongest score.
    Theme grade is never promoted to B merely because its score is high.
    """
    by_ticker: dict[str, EventSecurity] = {}
    grade_rank = {"A": 5, "B": 4, "THEME": 3, "PROXY": 2, "C": 1, "UNMAPPED": 0}

    for mapping in mappings:
        if not _matches_event(mapping, event):
            continue
        candidate = EventSecurity(
            event_id=event.event_id,
            ticker=mapping.ticker,
            relation_grade=mapping.relation_grade,
            relation_score=mapping.relation_score,
            relation_type=mapping.relation_type,
            evidence_text=(
                f"{mapping.company}: {mapping.evidence_text}" if mapping.company else mapping.evidence_text
            ),
        )
        current = by_ticker.get(mapping.ticker)
        if current is None:
            by_ticker[mapping.ticker] = candidate
            continue
        current_key = (grade_rank.get(current.relation_grade, 0), current.relation_score)
        candidate_key = (grade_rank.get(candidate.relation_grade, 0), candidate.relation_score)
        if candidate_key > current_key:
            by_ticker[mapping.ticker] = candidate

    return list(by_ticker.values())


def merge_event_securities(
    direct_rows: list[EventSecurity],
    theme_rows: list[EventSecurity],
) -> list[EventSecurity]:
    """Merge event-security rows, preferring stronger evidence per ticker."""
    grade_rank = {"A": 5, "B": 4, "THEME": 3, "PROXY": 2, "C": 1, "UNMAPPED": 0}
    merged: dict[str, EventSecurity] = {}

    for row in direct_rows + theme_rows:
        key = row.ticker or "__UNMAPPED__"
        current = merged.get(key)
        if current is None:
            merged[key] = row
            continue
        if (grade_rank.get(row.relation_grade, 0), row.relation_score) > (
            grade_rank.get(current.relation_grade, 0),
            current.relation_score,
        ):
            merged[key] = row

    real_rows = [row for key, row in merged.items() if key != "__UNMAPPED__"]
    if real_rows:
        real_rows.sort(
            key=lambda row: (grade_rank.get(row.relation_grade, 0), row.relation_score),
            reverse=True,
        )
        return real_rows
    return [merged["__UNMAPPED__"]] if "__UNMAPPED__" in merged else []
