# IPO / Convertible Noise Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Event Radar noise by emitting only IPO listing dates and only explicit convertible-to-new-share-listing events, while hiding already-stored legacy noise from the public dashboard.

**Architecture:** Narrow KIND and DART event-generation rules at the source for new ingestion. Preserve canonical history, but add an export compatibility filter so legacy KIND process milestones and generic convertible rows disappear from the dashboard immediately.

**Tech Stack:** Python 3.12, pytest, BeautifulSoup, requests

**Spec:** `docs/superpowers/specs/2026-11-03-trim-ipo-cb-noise.md`

## Global Constraints
- Preserve existing collector interfaces and error isolation.
- Keep CAPEX-backed rights issue behavior unchanged.
- Preserve canonical history.
- Do not add share-count/materiality integrations in this patch.
- Tests must demonstrate RED before production changes and GREEN afterward.

## Review Focus
- Headered KIND tables still identify listing dates correctly.
- Headerless KIND AJAX fragments still identify listing dates correctly.
- Calendar fallback emits only `상장` entries.
- Generic CB/BW titles do not leak into new events.
- Explicit conversion/exercise listings remain accepted.
- Legacy KIND milestones and generic convertible rows are hidden from site export without deleting canonical rows.

---

### Task 1: Compress KIND IPO events to listing only

**Files:**
- Modify: `tests/collectors/test_kind_ipo.py`
- Modify: `src/event_radar/collectors/kind_ipo.py`

- [x] Update KIND tests so sample table, program table, AJAX fragment, calendar fallback, and live fake session expect only listing events.
- [x] Verify RED from extra milestone events.
- [x] Remove bookbuilding/subscription/payment event generation; keep listing parsing and market proxy behavior.
- [x] Verify KIND behavior passes.

### Task 2: Narrow DART convertible classification

**Files:**
- Modify: `tests/collectors/test_dart.py`
- Modify: `src/event_radar/collectors/dart.py`

- [x] Add tests proving generic CB issuance/repricing/repurchase/sale are excluded and explicit `전환청구권행사(신주상장)` remains.
- [x] Verify RED under the former broad mapping.
- [x] Replace broad `전환사채`/`신주인수권`/`CB` mapping with an explicit exercise/conversion plus listing-evidence classifier.
- [x] Verify DART behavior passes.

### Task 3: Hide legacy dashboard noise without deleting history

**Files:**
- Modify: `tests/test_export_event_filter.py`
- Modify: `src/event_radar/export.py`

- [x] Add tests that old KIND process milestones are hidden while `IPO_LISTING` remains.
- [x] Add tests that generic historical DART convertible rows are hidden while actual conversion-to-listing rows remain.
- [x] Verify RED with only the two new export expectations failing.
- [x] Add the site visibility filter while keeping canonical rows intact.
- [x] Verify GREEN.

### Task 4: Full regression and live-source verification

- [x] Run the full pytest suite after collector implementation.
- [x] Verify NAVER API HUB credentials with a lightweight live collector diagnostic.
- [x] Verify live KIND emits only `IPO_LISTING` events.
- [x] Restore scheduled collection workflow and remove temporary diagnostic workflow.
- [x] Verify no temporary data/workflow files remain in the PR.
- [ ] Run final CI after documentation alignment and confirm the full suite is green.
