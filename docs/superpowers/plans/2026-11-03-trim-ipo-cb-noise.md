# IPO / Convertible Noise Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Event Radar noise by emitting only IPO listing dates and only explicit convertible-to-new-share-listing events.

**Architecture:** Keep the existing KIND and DART collectors, but narrow their event-generation rules at the source. No downstream scoring/export refactor is needed for new data.

**Tech Stack:** Python 3.12, pytest, BeautifulSoup, requests

**Spec:** `docs/superpowers/specs/2026-11-03-trim-ipo-cb-noise.md`

## Global Constraints
- Preserve existing collector interfaces and error isolation.
- Keep CAPEX-backed rights issue behavior unchanged.
- Do not add share-count/materiality integrations in this patch.
- Tests must demonstrate RED before production changes and GREEN afterward.

## Review Focus
- Headered KIND tables still identify listing dates correctly.
- Headerless KIND AJAX fragments still identify listing dates correctly.
- Calendar fallback emits only `상장` entries.
- Generic CB/BW titles do not leak into events.
- Explicit conversion/exercise listings remain accepted.

---

### Task 1: Compress KIND IPO events to listing only

**Files:**
- Modify: `tests/collectors/test_kind_ipo.py`
- Modify: `src/event_radar/collectors/kind_ipo.py`

**Interfaces:**
- Consumes: existing `KindIpoCollector.collect(since: datetime) -> list[RawEvent]`
- Produces: same interface, but only `IPO_LISTING` events.

- [ ] **Step 1:** Update KIND tests so sample table, program table, AJAX fragment, calendar fallback, and live fake session expect only listing events.
- [ ] **Step 2:** Run `pytest tests/collectors/test_kind_ipo.py -q` and verify failures are caused by extra milestone events.
- [ ] **Step 3:** Remove bookbuilding/subscription/payment event generation from `_parse_table` and `_events_from_calendar_entries`; keep listing parsing and market proxy behavior.
- [ ] **Step 4:** Run `pytest tests/collectors/test_kind_ipo.py -q` and verify all KIND tests pass.

### Task 2: Narrow DART convertible classification

**Files:**
- Modify: `tests/collectors/test_dart.py`
- Modify: `src/event_radar/collectors/dart.py`

**Interfaces:**
- Consumes: existing `DartCollector.collect(since: datetime) -> list[RawEvent]`
- Produces: `CONVERTIBLE_LISTING` only for explicit exercise/conversion-to-listing disclosures.

- [ ] **Step 1:** Add tests proving generic CB issuance/repricing/repurchase/sale are excluded and explicit `전환청구권행사(신주상장)` remains.
- [ ] **Step 2:** Run `pytest tests/collectors/test_dart.py -q` and verify new generic-CB tests fail under current broad mapping.
- [ ] **Step 3:** Replace broad `전환사채`/`신주인수권`/`CB` mapping with an explicit convertible-listing classifier requiring exercise/conversion language plus listing evidence.
- [ ] **Step 4:** Run `pytest tests/collectors/test_dart.py -q` and verify all DART tests pass.

### Task 3: Full regression and NEWS_FUTURE verification

**Files:**
- No production files unless a regression is found.

**Interfaces:**
- Consumes: Tasks 1-2 outputs.
- Produces: verified branch ready for PR.

- [ ] **Step 1:** Run full pytest suite.
- [ ] **Step 2:** Open PR with only source/test/docs changes.
- [ ] **Step 3:** Verify CI on PR head.
- [ ] **Step 4:** After code is stable, run one production collection from a temporary trigger only if needed to confirm the newly corrected NAVER API HUB credentials; restore the workflow immediately afterward.
