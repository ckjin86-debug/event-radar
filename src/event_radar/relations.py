"""Relation engine linking events to A/B grade securities with strict time awareness."""

from __future__ import annotations
import csv
from datetime import date
from pathlib import Path
from typing import Optional
from event_radar.entities import SecurityMention
from event_radar.models import Event, Relation, EventSecurity


def resolve_related_securities(
    event: Event,
    relations: list[Relation],
    direct_mentions: Optional[list[SecurityMention]] = None,
) -> list[EventSecurity]:
    """Resolve A/B related securities without look-ahead bias or theme guessing."""
    results: dict[str, EventSecurity] = {}
    mentions = direct_mentions or []

    primary_ticker = event.primary_ticker.strip().upper()
    primary_company = event.primary_company.strip().upper()

    # A broad market proxy is only a fallback. Once a listed issuer is directly named,
    # use the issuer(s) as the Grade-A securities instead of the proxy index.
    if primary_ticker and not (mentions and primary_ticker.startswith("^")):
        results[primary_ticker] = EventSecurity(
            event_id=event.event_id,
            ticker=primary_ticker,
            relation_grade="A",
            relation_score=100,
            relation_type="DIRECT",
            evidence_text="직접 당사자",
        )

    relation_origins = {value for value in (primary_ticker, primary_company) if value}
    for mention in mentions:
        ticker = mention.ticker.strip().upper()
        company = mention.company_name.strip()
        if not ticker:
            continue
        results[ticker] = EventSecurity(
            event_id=event.event_id,
            ticker=ticker,
            relation_grade="A",
            relation_score=100,
            relation_type="DIRECT_MENTION",
            evidence_text=f"직접 언급: {company}",
        )
        relation_origins.add(ticker)
        if company:
            relation_origins.add(company.upper())

    announced_date = event.announced_at.date() if hasattr(event.announced_at, "date") else event.announced_at
    event_date = event.event_date

    # Expand only from explicit primary/direct entities through stored evidence relations.
    for rel in relations:
        from_entity = rel.from_entity.strip().upper()
        if from_entity not in relation_origins:
            continue

        # Look-ahead bias check: was relation known before or on announcement?
        if rel.relation_known_date > announced_date:
            continue

        # Active period check
        if rel.relation_start_date > event_date:
            continue
        if rel.relation_end_date is not None and event_date > rel.relation_end_date:
            continue

        # Score threshold: B-grade candidate requires >= 60
        if rel.relation_score < 60:
            continue

        ticker = rel.to_ticker.strip().upper()
        if rel.relation_score >= 90:
            grade = "A"
        elif rel.relation_score >= 60:
            grade = "B"
        else:
            grade = "C"

        if grade == "C":
            continue

        candidate = EventSecurity(
            event_id=event.event_id,
            ticker=ticker,
            relation_grade=grade,
            relation_score=rel.relation_score,
            relation_type=rel.relation_type,
            evidence_text=rel.evidence_source,
        )

        # If already present, keep the higher score.
        if ticker in results:
            if candidate.relation_score > results[ticker].relation_score:
                results[ticker] = candidate
        else:
            results[ticker] = candidate

    return list(results.values())


def load_relations_csv(path: Path | str) -> list[Relation]:
    """Load canonical relations from CSV file."""
    path = Path(path)
    if not path.exists():
        return []

    relations: list[Relation] = []
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row or not row.get("relation_id"):
                continue
            end_date = row.get("relation_end_date")
            relations.append(
                Relation(
                    relation_id=row["relation_id"].strip(),
                    from_entity=row["from_entity"].strip(),
                    to_ticker=row["to_ticker"].strip().upper(),
                    relation_type=row.get("relation_type", "RELATED").strip(),
                    relation_grade=row.get("relation_grade", "B").strip(),  # type: ignore
                    relation_score=int(row.get("relation_score", 70)),
                    relation_known_date=date.fromisoformat(row["relation_known_date"].strip()[:10]),
                    relation_start_date=date.fromisoformat(row["relation_start_date"].strip()[:10]),
                    relation_end_date=date.fromisoformat(end_date.strip()[:10]) if end_date and end_date.strip() else None,
                    evidence_source=row.get("evidence_source", "").strip(),
                    source_url=row.get("source_url", "").strip(),
                    ingest_mode=row.get("ingest_mode", "AUTO").strip(),  # type: ignore
                )
            )
    return relations


def save_relations_csv(relations: list[Relation], path: Path | str) -> None:
    """Save relations to canonical CSV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "relation_id",
        "from_entity",
        "to_ticker",
        "relation_type",
        "relation_grade",
        "relation_score",
        "relation_known_date",
        "relation_start_date",
        "relation_end_date",
        "evidence_source",
        "source_url",
        "ingest_mode",
    ]
    with open(path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in relations:
            writer.writerow({
                "relation_id": r.relation_id,
                "from_entity": r.from_entity,
                "to_ticker": r.to_ticker,
                "relation_type": r.relation_type,
                "relation_grade": r.relation_grade,
                "relation_score": r.relation_score,
                "relation_known_date": r.relation_known_date.isoformat(),
                "relation_start_date": r.relation_start_date.isoformat(),
                "relation_end_date": r.relation_end_date.isoformat() if r.relation_end_date else "",
                "evidence_source": r.evidence_source,
                "source_url": r.source_url,
                "ingest_mode": r.ingest_mode,
            })
