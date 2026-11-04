"""Relation engine linking events to A/B grade securities with strict time awareness."""

from __future__ import annotations
import csv
from datetime import date
from pathlib import Path
from event_radar.entity_resolver import is_market_proxy
from event_radar.models import Event, Relation, EventSecurity


def _unmapped(event: Event, reason: str = "직접 또는 검증된 관련 종목 미매핑") -> list[EventSecurity]:
    return [
        EventSecurity(
            event_id=event.event_id,
            ticker="",
            relation_grade="UNMAPPED",
            relation_score=0,
            relation_type="UNMAPPED",
            evidence_text=reason,
        )
    ]


def _is_legacy_hidden_noise(event: Event) -> bool:
    """Match legacy canonical rows that the public radar intentionally hides."""
    if event.source_name == "DART" and event.event_type == "RIGHTS_ISSUE":
        return True
    if event.source_name == "KIND_IPO" and event.event_type != "IPO_LISTING":
        return True
    if event.source_name == "DART" and event.event_type == "CONVERTIBLE_LISTING":
        combined = f"{event.event_name} {event.evidence_text}".replace(" ", "")
        has_exercise = any(
            keyword in combined
            for keyword in ("전환청구권행사", "전환권행사", "신주인수권행사")
        )
        has_listing = "신주상장" in combined or "상장예정" in combined
        return not (has_exercise and has_listing)
    return False


def resolve_related_securities(event: Event, relations: list[Relation], knowledge_asof: date | None = None) -> list[EventSecurity]:
    """Resolve related securities for an event avoiding look-ahead bias and expired relations."""
    if _is_legacy_hidden_noise(event):
        return _unmapped(event, "레이더 비노출 레거시 이벤트")

    results: dict[str, EventSecurity] = {}
    announced_date = event.announced_at.date() if hasattr(event.announced_at, "date") else event.announced_at
    event_date = event.event_date
    known_cutoff = knowledge_asof if knowledge_asof and event_date >= knowledge_asof else announced_date

    # A real primary security is Grade A. Direct event rows are automatic event
    # evidence, not manual relation writeback, even when the event itself was edited.
    primary_ticker = event.primary_ticker.strip().upper()
    if primary_ticker:
        if is_market_proxy(primary_ticker):
            results[primary_ticker] = EventSecurity(
                event_id=event.event_id,
                ticker=primary_ticker,
                relation_grade="PROXY",
                relation_score=0,
                relation_type="MARKET_PROXY",
                evidence_text="시장/섹터 반응 참고용 프록시",
                evidence_source=event.source_name,
                source_url=event.source_url,
                relation_known_date=announced_date,
                ingest_mode="AUTO",
                from_entity=event.primary_company,
            )
        else:
            results[primary_ticker] = EventSecurity(
                event_id=event.event_id,
                ticker=primary_ticker,
                relation_grade="A",
                relation_score=100,
                relation_type="DIRECT",
                evidence_text="직접 당사자",
                evidence_source=event.source_name,
                source_url=event.source_url,
                relation_known_date=announced_date,
                ingest_mode="AUTO",
                from_entity=event.primary_company,
            )

    # A/B grade is an evidence classification, not a score bucket.
    for rel in relations:
        from_entity = rel.from_entity.strip().upper()
        if from_entity not in (primary_ticker, event.primary_company.strip().upper()):
            continue

        if rel.relation_known_date > known_cutoff:
            continue
        if rel.relation_start_date > event_date:
            continue
        if rel.relation_end_date is not None and event_date > rel.relation_end_date:
            continue

        grade = rel.relation_grade
        if grade not in {"A", "B"}:
            continue
        if grade == "A" and rel.relation_score < 90:
            continue
        if grade == "B" and rel.relation_score < 60:
            continue

        ticker = rel.to_ticker.strip().upper()
        if not ticker or is_market_proxy(ticker):
            continue

        candidate = EventSecurity(
            event_id=event.event_id,
            ticker=ticker,
            relation_grade=grade,
            relation_score=rel.relation_score,
            relation_type=rel.relation_type,
            evidence_text=rel.evidence_source,
            evidence_source=rel.evidence_source,
            source_url=rel.source_url,
            relation_known_date=rel.relation_known_date,
            ingest_mode=rel.ingest_mode,
            from_entity=rel.from_entity,
        )

        if ticker in results:
            if candidate.relation_score > results[ticker].relation_score:
                results[ticker] = candidate
        else:
            results[ticker] = candidate

    if not results:
        return _unmapped(event)

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
    """Save relations to canonical CSV file."""
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
