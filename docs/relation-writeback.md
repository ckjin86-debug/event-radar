# AI Relation Discovery → Verify → Writeback

Event Radar intentionally separates broad candidate discovery from permanent relation knowledge.

## Flow

`EVENT RADAR → candidate securities → AI_RELATION_DISCOVERY → VERIFY → WRITEBACK`

- Event Radar may emit A/B/THEME/PROXY/UNMAPPED candidates for analysis.
- bb-invest or another verifier may search additional web, disclosure, IR, government, exchange, or contract evidence.
- Only verified **A** or **B** relations are persisted to `data/canonical/manual_relations.csv`.
- C/THEME/PROXY relations remain temporary analysis context and are never permanent graph edges.

## Grade semantics

- **A — DIRECT**: the listed company is a direct party to the event/transaction/decision.
- **B — VERIFIED ECONOMIC RELATION**: supply, contract, ownership, JV, EPC, investment, customer/vendor, or other economic link supported by evidence.
- **C / THEME**: narrative, industry, political, sympathy, or estimated beneficiary. Temporary only.
- **PROXY**: index/ETF/sector proxy. Never persisted as a company relation.

`relation_score` is confidence/strength **inside the assigned grade**. A high B score does not promote B into A.

## Permanent writeback gate

A proposed row is eligible only when all of the following hold:

1. `relation_grade` is A or B.
2. A has `relation_score >= 90`; B has `relation_score >= 60`.
3. `from_entity`, `to_ticker`, and `relation_type` are explicit.
4. `to_ticker` is a tradable company security, not a market/sector proxy.
5. `relation_known_date` is the earliest date the relation was publicly knowable; do not backdate from later research.
6. `relation_start_date` reflects when the relationship became effective or first existed.
7. `evidence_source` contains the verified factual basis.
8. `source_url` is an absolute HTTP(S) evidence URL.
9. Prefer regulator/exchange/company IR/government/official contract sources. High-quality secondary reporting may support discovery, but weak theme articles alone do not qualify for permanent writeback.

## Schema

`manual_relations.csv` uses:

`relation_id,from_entity,to_ticker,relation_type,relation_grade,relation_score,relation_known_date,relation_start_date,relation_end_date,evidence_source,source_url,ingest_mode`

Manual rows use `ingest_mode=MANUAL`.

## Upsert rule

The durable relation key is `from_entity + to_ticker`.

- New key → `CREATED`.
- Existing key with stronger/new evidence → `UPDATED`.
- Identical content → `UNCHANGED`.
- Updates preserve the existing `relation_id` and earliest known/start dates to avoid duplicate edges and look-ahead bias.

Use `scripts/writeback_relation.py` for validated local writes. When an agent writes through GitHub, it must fetch the current `manual_relations.csv` first and update against the current file revision to avoid overwriting concurrent changes.

## Downstream behavior

On the next Event Radar collection, `manual_relations.csv` overrides the auto relation for the same entity+ticker pair and becomes available to event mapping and backtests. Writeback failure does not alter the current investment verdict; it only means the learned relation was not persisted.
