# Event Sources v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent News Future, FDA, KIND IPO, and FOMC collectors with fuzzy-date support and graceful degradation.

**Architecture:** Each source is its own collector returning `RawEvent` into the existing normalize/dedupe/pipeline. Backward-compatible date-window fields are added to raw/canonical models and CSV/site exports. Optional NAVER credentials disable only the news source.

**Tech Stack:** Python 3.12, requests, BeautifulSoup, pydantic, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-03-event-sources-v2.md`

## Global Constraints
- Existing DART/SEC behavior must remain green.
- No fake/synthetic production events.
- Missing one source or optional credential must not break the pipeline.
- Generic rights-issue noise remains excluded; capex financing remains allowed.
- Period-type news must not be displayed as an exact date.

## Review Focus
- Month/quarter/year rollover around December/January.
- Duplicate news articles pointing to the same future event.
- HTML selector drift on FDA/KIND/Fed pages.
- KIND companies without a listed ticker.
- Macro proxy tickers must not break price/backtest code.

---

### Task 1: Date-window model support
**Files:** modify `src/event_radar/models.py`, `src/event_radar/pipeline.py`, `src/event_radar/export.py`; test `tests/test_date_windows.py`.
**Produces:** optional `date_precision`, `window_start`, `window_end` on RawEvent/Event and persistence/export support.
- [ ] Write failing round-trip/export tests for MONTH and EXACT_DATE.
- [ ] Verify RED.
- [ ] Implement minimal backward-compatible fields and CSV/site output.
- [ ] Verify focused tests and full suite GREEN.

### Task 2: News future event collector
**Files:** create `src/event_radar/collectors/news_future.py`; test `tests/collectors/test_news_future.py`.
**Produces:** `NewsFutureCollector.collect(since) -> list[RawEvent]` and deterministic future-expression parsing.
- [ ] Write failing tests for `내달`, explicit month, exact day, no-catalyst rejection, rights-issue exclusion, capex exception, and missing credentials.
- [ ] Verify RED.
- [ ] Implement NAVER API HUB adapter using `NAVER_API_HUB_KEY_ID`/`NAVER_API_HUB_KEY` and filters.
- [ ] Verify focused and full suite GREEN.

### Task 3: FDA advisory calendar collector rebuild
**Files:** replace `src/event_radar/collectors/fda.py`; update `tests/collectors/test_registry.py` or create `tests/collectors/test_fda.py`.
**Produces:** official advisory meeting events; sector proxy `XBI` when no direct ticker mapping exists.
- [ ] Write failing tests from representative official-calendar HTML.
- [ ] Verify RED.
- [ ] Implement official calendar parsing and graceful failures.
- [ ] Verify focused and full suite GREEN.

### Task 4: KIND IPO collector
**Files:** create `src/event_radar/collectors/kind_ipo.py`; test `tests/collectors/test_kind_ipo.py`.
**Produces:** demand forecast, subscription, payment, and listing-date events with KOSPI/KOSDAQ proxy tickers when necessary.
- [ ] Write failing parsing tests for row with date ranges and listing date.
- [ ] Verify RED.
- [ ] Implement parser and source UIDs.
- [ ] Verify focused and full suite GREEN.

### Task 5: FOMC collector
**Files:** create `src/event_radar/collectors/fomc.py`; test `tests/collectors/test_fomc.py`.
**Produces:** `FOMC_DECISION` events on final meeting date using `^GSPC`.
- [ ] Write failing tests for one-day and two-day meetings.
- [ ] Verify RED.
- [ ] Implement official Fed calendar parser.
- [ ] Verify focused and full suite GREEN.

### Task 6: Production wiring and docs
**Files:** modify `scripts/collect.py`, `.github/workflows/collect.yml`, `README.md`, `tests/test_collect_script.py`.
**Consumes:** collectors from Tasks 2-5.
- [ ] Write failing test asserting all four collectors are wired and NAVER secrets are optional env vars.
- [ ] Verify RED.
- [ ] Wire collectors; add optional Actions env entries; document NAVER API HUB setup.
- [ ] Run full suite.
- [ ] Open PR and inspect diff/CI before merge.
