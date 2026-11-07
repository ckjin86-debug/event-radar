"""Pilot spot-check: SEC 13D/13G primary_doc.xml parsing, production vs edgartools.

Discovery stays with the production collector's EDGAR full-text search
(efts) — edgartools' per-company ``get_filings`` does not surface
subject-company 13D/13G filings the way Event Radar needs. Only the XML
parsing step is compared:

- Baseline: ``SecFivePctCollector._parse_primary_doc`` (regex tag reads)
  on the live primary_doc.xml.
- Pilot:    the same filing as an edgartools ``Filing`` -> ``.obj()``
  (``Schedule13D`` / ``Schedule13G``).

Key semantics found by this check (2026-11-07 run): for multi-person
filings the production collector models the FIRST reporting person in
document order, while edgartools' ``total_percent`` / ``total_shares``
reflect the aggregate/control person. ``reporting_persons[0]`` in
edgartools matches the production values exactly, so a migration can
preserve current semantics — but it must choose person [0] explicitly
rather than taking the schedule totals.

Usage (pilot venv):
    python scripts/pilot_edgartools_13dg_check.py --since 2026-11-03 --max 3
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from event_radar.collectors.sec import SEC_DEFAULT_USER_AGENT  # noqa: E402
from event_radar.collectors.sec_five_pct import SecFivePctCollector  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2026-11-03")
    parser.add_argument("--max", type=int, default=3)
    args = parser.parse_args()

    import edgar
    from edgar.entity.filings import Filing

    edgar.set_identity(SEC_DEFAULT_USER_AGENT)

    base = SecFivePctCollector()
    hits = base._discover_hits(datetime.fromisoformat(args.since), None)

    results: list[dict] = []
    for hit in hits:
        if len(results) >= args.max:
            break
        src = hit.get("_source") or {}
        adsh = str(src.get("adsh") or "")
        ciks = src.get("ciks") or []
        form = str(src.get("form") or "")
        if not adsh or not ciks:
            continue

        xml = base._load_primary_doc_xml(str(ciks[0]), adsh, None)
        parsed = base._parse_primary_doc(xml)
        if parsed is None:
            continue

        filing = Filing(
            cik=int(str(ciks[0]).lstrip("0") or "0"),
            company="",
            form=form,
            filing_date=str(src.get("file_date") or "")[:10],
            accession_no=adsh,
        )
        try:
            obj = filing.obj()
        except Exception as exc:  # noqa: BLE001 - recorded per filing
            results.append(
                {"form": form, "accession": adsh, "edgartools_error": f"{type(exc).__name__}: {exc}"}
            )
            continue

        persons = []
        for rp in getattr(obj, "reporting_persons", []) or []:
            persons.append(
                {
                    "name": getattr(rp, "name", None),
                    "percent_of_class": getattr(rp, "percent_of_class", None),
                    "aggregate_amount": getattr(rp, "aggregate_amount", None),
                }
            )
        results.append(
            {
                "form": form,
                "accession": adsh,
                "baseline_first_person": {
                    "percent_of_class": parsed["percent_of_class"],
                    "numeric_shares": parsed["numeric_shares"],
                    "reporting_person_name": parsed["reporting_person_name"],
                },
                "edgartools_totals": {
                    "total_percent": getattr(obj, "total_percent", None),
                    "total_shares": getattr(obj, "total_shares", None),
                },
                "edgartools_reporting_persons": persons,
                "persons0_matches_baseline": bool(persons)
                and persons[0]["percent_of_class"] == parsed["percent_of_class"]
                and persons[0]["aggregate_amount"] == parsed["numeric_shares"]
                and persons[0]["name"] == parsed["reporting_person_name"],
            }
        )

    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
