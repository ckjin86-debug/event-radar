"""Guarded persistence for AI-verified A/B relations.

This module is the permanent-knowledge boundary for relations discovered outside the
collector pipeline.  Candidate/theme relationships may be analyzed elsewhere, but
only evidence-backed A/B relations are allowed into manual_relations.csv.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from event_radar.entity_resolver import is_market_proxy
from event_radar.models import Relation
from event_radar.relations import load_relations_csv, save_relations_csv


class RelationWritebackError(ValueError):
    """Raised when a proposed permanent relation fails the writeback gate."""


def _relation_key(relation: Relation) -> tuple[str, str]:
    return (
        relation.from_entity.strip().upper(),
        relation.to_ticker.strip().upper(),
    )


def validate_verified_relation(relation: Relation) -> None:
    """Validate the permanent A/B knowledge contract.

    A means a direct party. B means a verified economic relationship. Scores express
    confidence/strength inside the grade and must never promote B into A.
    """
    if relation.relation_grade not in {"A", "B"}:
        raise RelationWritebackError("permanent writeback accepts only A or B relations")
    if not relation.from_entity.strip():
        raise RelationWritebackError("from_entity is required")
    if not relation.to_ticker.strip():
        raise RelationWritebackError("to_ticker is required")
    if is_market_proxy(relation.to_ticker.strip().upper()):
        raise RelationWritebackError("market/index/sector proxies cannot be permanently registered")
    if not relation.relation_type.strip():
        raise RelationWritebackError("relation_type is required")
    if relation.relation_grade == "A" and relation.relation_score < 90:
        raise RelationWritebackError("A relations require relation_score >= 90")
    if relation.relation_grade == "B" and relation.relation_score < 60:
        raise RelationWritebackError("B relations require relation_score >= 60")
    if not relation.evidence_source.strip():
        raise RelationWritebackError("evidence_source is required")
    if not relation.source_url.strip():
        raise RelationWritebackError("source_url is required")
    parsed = urlparse(relation.source_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RelationWritebackError("source_url must be an absolute http(s) URL")
    if relation.relation_end_date and relation.relation_end_date < relation.relation_start_date:
        raise RelationWritebackError("relation_end_date cannot precede relation_start_date")


def upsert_verified_relation(
    existing: list[Relation],
    proposed: Relation,
) -> tuple[list[Relation], str]:
    """Insert/update one verified relation keyed by entity+ticker.

    The original relation_id and earliest known/start dates are retained on updates so
    later evidence refreshes do not create look-ahead bias or duplicate graph edges.
    """
    validate_verified_relation(proposed)
    normalized = proposed.model_copy(
        update={
            "from_entity": proposed.from_entity.strip(),
            "to_ticker": proposed.to_ticker.strip().upper(),
            "relation_type": proposed.relation_type.strip().upper(),
            "evidence_source": proposed.evidence_source.strip(),
            "source_url": proposed.source_url.strip(),
            "ingest_mode": "MANUAL",
        }
    )
    target_key = _relation_key(normalized)
    rows = list(existing)

    for index, current in enumerate(rows):
        if _relation_key(current) != target_key:
            continue
        merged = normalized.model_copy(
            update={
                "relation_id": current.relation_id,
                "relation_known_date": min(current.relation_known_date, normalized.relation_known_date),
                "relation_start_date": min(current.relation_start_date, normalized.relation_start_date),
                "ingest_mode": "MANUAL",
            }
        )
        if merged == current:
            return rows, "UNCHANGED"
        rows[index] = merged
        return rows, "UPDATED"

    rows.append(normalized)
    return rows, "CREATED"


def upsert_verified_relation_csv(path: Path | str, proposed: Relation) -> str:
    """Validate and persist a relation into manual_relations.csv."""
    path = Path(path)
    existing = load_relations_csv(path)
    rows, status = upsert_verified_relation(existing, proposed)
    save_relations_csv(rows, path)
    return status
