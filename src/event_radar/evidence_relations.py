"""Conservative, dated economic relationships derived from explicit article pairs."""

from __future__ import annotations

import hashlib
import re
from datetime import date

from event_radar.entity_resolver import ListedCompanyRegistry
from event_radar.models import Event, Relation


def discover_relations(events: list[Event], registry: ListedCompanyRegistry, as_of: date) -> list[Relation]:
    """Extract explicit counterparties; never infer an industry supply chain.

    Derived rows are reproducible evidence, not permanent manual DB writeback.
    Each relationship keeps its article publication date and quoted clause.
    """
    rows: dict[str, Relation] = {}
    for event in events:
        known = event.announced_at.date()
        if event.country != 'KR' or known > as_of or not event.source_url:
            continue
        text = event.evidence_text or event.event_name
        for clause in re.split(r'[。！？;]|(?<!\d)[.,!?]|[.,!?](?!\d)', text):
            if re.search(r'검토|예정|추진|가능|협의|협상|미정|루머|보류|부인|없|않|무관|비교|경쟁|반면|고객사|해당\s*업체', clause):
                continue
            mentions = registry.mentioned_companies(clause)
            if len(mentions) != 2:
                continue
            (first, first_code), (second, second_code) = mentions
            # Both companies must be the endpoints of the same supported phrase.
            pair = re.search(re.escape(first) + r'\s*(?:는|은|가|이|와|과|·|,)?\s*' + re.escape(second)
                             + r'\s*(?:와|과|에|에게|의|는|은|가|이)(?P<tail>.{0,65})', clause)
            if not pair:
                continue
            tail = pair.group('tail')
            if re.search(r'(?:공급|납품|판매).{0,12}계약.{0,12}(?:체결|맺)', tail):
                kind, score = 'SUPPLY_CONTRACT', 78
            elif re.search(r'지분.{0,15}(?:보유|취득|인수)|최대\s*주주|모회사|자회사', tail):
                kind, score = 'OWNERSHIP_LINK', 82
            elif re.search(r'투자.{0,12}(?:집행|완료|했다|했)|출자.{0,12}(?:완료|했다|했)', tail):
                kind, score = 'INVESTMENT_LINK', 72
            else:
                continue
            for anchor, ticker in ((first_code, second_code), (second_code, first_code)):
                uid = hashlib.sha1(f'{anchor}|{ticker}|{kind}|{event.source_url}'.encode()).hexdigest()[:20]
                rows[uid] = Relation(relation_id=f'DERIVED_{uid}', from_entity=anchor, to_ticker=ticker,
                    relation_type=kind, relation_grade='B', relation_score=score,
                    relation_known_date=known, relation_start_date=known,
                    evidence_source=f'{event.source_name}: {clause.strip()}', source_url=event.source_url)
    return list(rows.values())
