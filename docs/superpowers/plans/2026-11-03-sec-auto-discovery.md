# SEC Automatic Filing Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove manual `SEC_CIKS` configuration and automatically discover relevant U.S. public-company 8-K filings from SEC daily indexes.

**Architecture:** `SecCollector` will use recent SEC EDGAR daily master indexes as the discovery layer, filter to 8-K/8-K-A candidates, resolve CIKs to tickers from SEC company mappings, and fetch submissions JSON only for candidate companies to classify supported Event Radar events. Existing fixture mode remains deterministic for tests, and all normalized events continue through the existing pipeline unchanged.

**Tech Stack:** Python 3.12, requests, pytest, GitHub Actions, SEC EDGAR public files/APIs

**Spec:** `docs/superpowers/specs/2026-11-03-sec-auto-discovery-design.md`

## Global Constraints

- No manual `SEC_CIKS` production configuration.
- No SEC API key or secret.
- Keep automated SEC traffic comfortably below 10 requests/second.
- Preserve fixture-based SEC tests.
- A failed SEC request must not crash the multi-source pipeline.
- Historical multi-year SEC backfill is out of scope.

## Review Focus

- Today/weekend/holiday daily-index files may not exist; missing dates must be skipped without losing other dates.
- Multiple 8-K rows for one CIK should cause at most one submissions lookup for that CIK in a run.
- An unrelated 8-K must not become an Event Radar event.
- A CIK with no ticker mapping must be skipped rather than assigned a fabricated ticker.
- One candidate company's enrichment failure must not discard events from other companies.

---

### Task 1: Daily index discovery and identity mapping

**Files:**
- Modify: `src/event_radar/collectors/sec.py`
- Modify: `tests/collectors/test_sec.py`

**Interfaces:**
- Produces: `SecCollector._parse_master_index(text: str) -> list[dict]`
- Produces: `SecCollector._load_company_tickers() -> dict[str, tuple[str, str]]`
- Produces: recent discovery candidates containing CIK, form, filing date, and filing path.

- [ ] **Step 1: Write failing tests** for 8-K/8-K-A filtering, non-8-K exclusion, CIK/ticker mapping, missing-index tolerance, and duplicate CIK candidate handling.
- [ ] **Step 2: Run SEC collector tests and verify RED** because discovery helpers do not exist.
- [ ] **Step 3: Implement minimal daily-index parsing, recent-date URL generation (max 3 calendar days), mapping fetch/cache, and candidate dedupe.**
- [ ] **Step 4: Run SEC collector tests and verify GREEN.**
- [ ] **Step 5: Commit.**

### Task 2: Candidate enrichment and event classification

**Files:**
- Modify: `src/event_radar/collectors/sec.py`
- Modify: `tests/collectors/test_sec.py`

**Interfaces:**
- Consumes: Task 1 discovery candidates and CIK mapping.
- Produces: supported `RawEvent` objects using existing event classification semantics.

- [ ] **Step 1: Write failing tests** proving automatic discovery returns earnings/split events without `SEC_CIKS`, unrelated 8-Ks are ignored, and one failed company enrichment does not erase successful companies.
- [ ] **Step 2: Run SEC collector tests and verify RED.**
- [ ] **Step 3: Refactor fixture parsing into reusable payload parsing and implement per-CIK submissions enrichment matched by accession number.**
- [ ] **Step 4: Run SEC collector tests and full pytest suite; verify GREEN.**
- [ ] **Step 5: Commit.**

### Task 3: Remove manual SEC configuration from operations

**Files:**
- Modify: `.github/workflows/collect.yml`
- Modify: `tests/test_collect_script.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `SecCollector()` with no watchlist configuration.
- Produces: scheduled workflow requiring only existing non-SEC secrets such as `DART_API_KEY`.

- [ ] **Step 1: Change the workflow test to require absence of `SEC_CIKS` and document automatic SEC discovery.**
- [ ] **Step 2: Run tests and verify RED while workflow still references `SEC_CIKS`.**
- [ ] **Step 3: Remove `SEC_CIKS` from the workflow and README setup instructions; explain automatic U.S. discovery.**
- [ ] **Step 4: Run the complete pytest suite and verify GREEN.**
- [ ] **Step 5: Open/update PR and verify GitHub Actions on the branch.**
