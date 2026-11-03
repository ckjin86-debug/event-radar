# Related Securities + News Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve directly named listed companies to Grade A securities, preserve evidence-only Grade B expansion, and moderately increase NEWS_FUTURE recall without restoring noise.

**Architecture:** Add a focused entity-universe module that loads official KR/US issuer mappings and resolves company mentions. Feed those direct matches into the existing relation engine before its dated relation expansion. Tune NEWS_FUTURE queries/window rules independently, preserving the current title-level precision filters and clustering.

**Tech Stack:** Python 3.12, requests, zipfile/xml.etree, pytest, existing Pydantic models.

**Spec:** `docs/superpowers/specs/2026-11-03-related-securities-news-recall.md`

## Global Constraints
- Direct company mention => Grade A, score 100.
- Grade B requires stored relation evidence with score >= 60 and existing look-ahead/time-window checks.
- No theme-only inference.
- PRODUCT_LAUNCH stays exact-date only.
- Listing remains excluded from NEWS_FUTURE because KIND is authoritative.

## Review Focus
- Company aliases/suffixes such as `(주)`, `주식회사`, Corp./Inc. should normalize without creating substring false matches.
- A market proxy ticker such as `^KS11` must not remain as the primary Grade A security after a direct issuer match exists.
- Multiple direct issuers in one title should all be Grade A.
- Official entity source failures must degrade gracefully instead of breaking collection.
- Relation expansion must still reject future-known and expired relationships.

---

### Task 1: Official issuer universe and direct mention resolution

**Files:**
- Create: `src/event_radar/entities.py`
- Create: `tests/test_entities.py`

**Interfaces:**
- Produces: `SecurityMention(company_name: str, ticker: str, country: str)`
- Produces: `EntityUniverse.resolve_mentions(text: str, country: str) -> list[SecurityMention]`
- Produces: `load_entity_universe(dart_api_key: str = "", session=None) -> EntityUniverse`

- [ ] Write tests for KR/US payload parsing, normalization, multi-company mention matching, and graceful source failure.
- [ ] Run targeted tests and verify RED.
- [ ] Implement the minimal entity universe loaders and matcher.
- [ ] Run targeted tests and verify GREEN.

### Task 2: Feed direct mentions into A/B relation resolution

**Files:**
- Modify: `src/event_radar/relations.py`
- Modify: `src/event_radar/pipeline.py`
- Modify: `tests/test_relations.py`
- Modify: `tests/integration/test_pipeline.py`

**Interfaces:**
- Consumes: `EntityUniverse.resolve_mentions(...)`
- Produces: `resolve_related_securities(event, relations, direct_mentions=None)` with backward-compatible default.

- [ ] Add failing tests proving `^KS11` is replaced by named issuer A-grade matches, multiple direct issuers are retained, and evidence relation expansion can originate from a direct mention.
- [ ] Run tests and verify RED.
- [ ] Implement direct mention seeding and pipeline universe loading once per run.
- [ ] Run tests and verify GREEN.

### Task 3: Moderate NEWS_FUTURE recall

**Files:**
- Modify: `src/event_radar/collectors/news_future.py`
- Modify: `tests/collectors/test_news_future.py`

**Interfaces:**
- Keeps existing collector output shape.

- [ ] Add failing tests for high-impact month-window events and new high-impact query coverage while preserving exact-date-only product launch and listing exclusion.
- [ ] Run tests and verify RED.
- [ ] Expand default queries and actionable-window logic minimally.
- [ ] Run tests and verify GREEN.

### Task 4: Full regression + live diagnostic

**Files:**
- Temporary workflow only if needed for live secrets; remove before PR finalization.

- [ ] Run the full pytest suite and verify zero failures.
- [ ] Run a live 7-day NEWS_FUTURE/entity diagnostic with GitHub Actions secrets.
- [ ] Inspect survivor count and samples; only tune further if obvious false positives dominate.
- [ ] Remove temporary diagnostics and generated data from the branch.
- [ ] Run the full pytest suite again on the cleaned head.
