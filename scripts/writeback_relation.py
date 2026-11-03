"""Write one verified A/B relation into Event Radar manual knowledge."""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from event_radar.manual.relation_writeback import upsert_verified_relation_csv
from event_radar.models import Relation


def _relation_id(from_entity: str, ticker: str) -> str:
    key = f"{from_entity.strip().upper()}|{ticker.strip().upper()}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12].upper()
    return f"BBREL_{digest}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persist one verified Event Radar relation")
    parser.add_argument("--from-entity", required=True)
    parser.add_argument("--to-ticker", required=True)
    parser.add_argument("--relation-type", required=True)
    parser.add_argument("--grade", choices=["A", "B"], required=True)
    parser.add_argument("--score", type=int, required=True)
    parser.add_argument("--known-date", type=date.fromisoformat, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--evidence-source", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--relation-id")
    parser.add_argument(
        "--path",
        type=Path,
        default=ROOT / "data" / "canonical" / "manual_relations.csv",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    relation = Relation(
        relation_id=args.relation_id or _relation_id(args.from_entity, args.to_ticker),
        from_entity=args.from_entity,
        to_ticker=args.to_ticker,
        relation_type=args.relation_type,
        relation_grade=args.grade,
        relation_score=args.score,
        relation_known_date=args.known_date,
        relation_start_date=args.start_date,
        relation_end_date=args.end_date,
        evidence_source=args.evidence_source,
        source_url=args.source_url,
        ingest_mode="MANUAL",
    )
    status = upsert_verified_relation_csv(args.path, relation)
    print(f"RELATION_WRITEBACK_STATUS={status}")


if __name__ == "__main__":
    main()
