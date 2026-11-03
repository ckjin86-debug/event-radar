# Event Stock Resolver v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase future-event recall and convert event text/IPO schedules into evidence-backed tradable stock mappings without promoting market proxies to direct A/B candidates.

**Architecture:** Keep collectors responsible for event discovery, add a reusable listed-company registry/resolver for entity-to-ticker mapping, and add a bounded IPO relationship enricher that returns event-specific securities. Merge direct mentions, canonical relations, IPO enrichment, and theme mappings in the pipeline with explicit grade precedence.

**Tech Stack:** Python 3.12, requests, pandas, Pydantic, pytest, OpenDART, Naver API Hub, GitHub Actions/Pages.

**Spec:** `docs/superpowers/specs/2026-11-03-event-stock-resolver-v2.md`

## Global Constraints

- Existing collectors must degrade gracefully on external API failures.
- Generic rights issues remain excluded unless facility/CAPEX-backed.
- KIND remains authoritative for IPO listing dates.
- Market/sector proxies never qualify as A/B direct-company candidates.
- IPO B mappings require explicit relationship evidence.
- Existing historical/theme/backtest behavior must remain intact.

## Review Focus

- Description-only dates/catalysts must not create events when the date and catalyst occur in unrelated clauses.
- Company-name matching must avoid short/ambiguous substring false positives.
- A failed OpenDART corp registry load must leave events usable rather than fail the pipeline.
- IPO enrichment must not turn mere co-mentions or same-industry articles into B mappings.
- Proxy rows must remain visible as informational mappings but must not become A/B after merge.

---

### Task 1: Expand future-news recall without dropping temporal precision

**Files:**
- Modify: `src/event_radar/collectors/news_future.py`
- Modify: `tests/collectors/test_news_future.py`

**Interfaces:**
- Consumes: Naver payload title/description and existing `parse_future_window`, `classify_catalyst` helpers.
- Produces: higher-recall `RawEvent` rows with the same model contract.

- [ ] Add failing tests proving a catalyst/date in the same description clause is accepted, while unrelated title/description clauses are rejected.
- [ ] Add a failing test proving the default query set covers at least 25 targeted future-catalyst searches including court, M&A, CAPEX, policy, tender, control dispute, election, clinical, approval, and operation terms.
- [ ] Update collection to evaluate combined title+description for window, catalyst, and temporal linkage while keeping company extraction title-first.
- [ ] Expand `DEFAULT_QUERIES` with targeted future-catalyst searches.
- [ ] Run `pytest tests/collectors/test_news_future.py -v` and confirm all pass.

### Task 2: Resolve listed-company mentions and isolate market proxies

**Files:**
- Create: `src/event_radar/entity_resolver.py`
- Modify: `src/event_radar/models.py`
- Modify: `src/event_radar/relations.py`
- Create: `tests/test_entity_resolver.py`
- Modify: `tests/test_relations.py`

**Interfaces:**
- Produces: `ListedCompanyRegistry.resolve_mentions(event: Event) -> list[EventSecurity]` and `is_market_proxy(ticker: str) -> bool`.
- Consumes later: pipeline Task 4.

- [ ] Add failing tests for normalized Korean company-name matching (`한화시스템` -> `272210`, `삼성바이오로직스` -> `207940`) and for rejecting short/partial names.
- [ ] Add failing tests that `^KS11`, `^KQ11`, `^GSPC`, and `XBI` map to `PROXY`, not `A`.
- [ ] Implement cached OpenDART `corpCode.xml` registry loading and fixture-friendly constructors.
- [ ] Add `PROXY` to `RelationGrade` and update relation merge/ranking semantics accordingly.
- [ ] Run entity/resolution tests and regression relation tests.

### Task 3: Remove IPO index proxies and enrich IPOs with evidence-backed listed relations

**Files:**
- Modify: `src/event_radar/collectors/kind_ipo.py`
- Modify: `tests/collectors/test_kind_ipo.py`
- Create: `src/event_radar/ipo_enrichment.py`
- Create: `tests/test_ipo_enrichment.py`

**Interfaces:**
- Produces: `IpoRelationEnricher.enrich(event: Event, registry: ListedCompanyRegistry) -> list[EventSecurity]`.
- Consumes: Naver credentials, listed-company registry.
- Consumed by: pipeline Task 4.

- [ ] Change KIND tests so IPO events carry an empty `primary_ticker` and preserve market only as raw/evidence metadata.
- [ ] Add failing enrichment tests: largest shareholder/parent and disclosed investor produce B mappings; same-industry co-mention does not.
- [ ] Implement bounded Naver relationship queries and evidence classification (`IPO_PARENT`, `IPO_MAJOR_SHAREHOLDER`, `IPO_INVESTOR`, `IPO_AFFILIATE`, `IPO_BUSINESS_RELATION`).
- [ ] Gracefully return no rows when Naver credentials or registry are unavailable.
- [ ] Run KIND and IPO enrichment tests.

### Task 4: Integrate resolver/enrichment into pipeline and verify live output

**Files:**
- Modify: `src/event_radar/pipeline.py`
- Modify: `src/event_radar/theme.py`
- Modify: `scripts/collect.py` if constructor wiring is required.
- Create/Modify: `tests/test_pipeline_stock_resolution.py`
- Modify: UI only if `PROXY` badge needs explicit neutral rendering.

**Interfaces:**
- Consumes: `ListedCompanyRegistry`, canonical relations, IPO enrichment, theme mappings.
- Produces: refreshed `event_security_map.csv`, `events.json`, `event_details.json` consumed by bb-invest and Pages.

- [ ] Add failing integration tests proving an unmapped news event with `한화시스템` becomes A/272210, an IPO no longer yields index A, and an IPO enrichment row survives merge as B.
- [ ] Wire registry/direct mentions and IPO enrichment before theme merge; keep strongest mapping per ticker with precedence A > B > THEME > PROXY > UNMAPPED.
- [ ] Ensure proxy securities are skipped for stock-price backtest fetches when appropriate while preserving display context.
- [ ] Run the full test suite.
- [ ] Open PR, verify CI, merge to `main` after explicit user authorization already given in the current conversation.
- [ ] Trigger live collection through the existing run-now sentinel, verify collector counts, mapped A/B rows, and Pages deployment; compare against the prior 29-event / 4-news snapshot.