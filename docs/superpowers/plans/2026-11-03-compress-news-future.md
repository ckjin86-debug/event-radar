# NEWS_FUTURE Compression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce noisy NEWS_FUTURE article-level candidates into a smaller set of market-relevant future-event clusters and refresh the public dashboard data after merge.

**Architecture:** Keep the existing `NewsFutureCollector` and add stricter classification/linkage helpers plus cluster-level deduplication before emitting `RawEvent`s. Official listing data remains owned by KIND. After merge, run the collection pipeline once so the site JSON and Pages deployment reflect both this change and the prior IPO/CB filters.

**Tech Stack:** Python 3.12, pytest, requests, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-11-03-compress-news-future.md`

## Global Constraints
- Do not add a new external dependency.
- Keep missing NAVER credentials non-fatal.
- Keep official-source collectors unchanged.
- Preserve market-wide strong events when `^KS11` is appropriate.
- Use TDD for behavior changes.

## Review Focus
- Same event returned by multiple queries/news outlets emits one event.
- A future date unrelated to the catalyst does not create an event.
- Consumer promotions/discounts are not classified as product launches.
- Exact-date meaningful launches still survive.
- Broad date windows survive only for high-impact event types.

---

### Task 1: Tighten NEWS_FUTURE classification and date linkage

**Files:**
- Modify: `tests/collectors/test_news_future.py`
- Modify: `src/event_radar/collectors/news_future.py`

**Interfaces:**
- Consumes: `parse_future_window(text, reference_date)` and `classify_catalyst(text)`.
- Produces: stricter catalyst classification plus a helper that validates temporal/catalyst proximity.

- [ ] **Step 1:** Add failing tests for LISTING rejection, promotion-only launch rejection, explicit meaningful launch retention, unrelated date/catalyst rejection, and broad-window high-impact gating.
- [ ] **Step 2:** Run NEWS_FUTURE tests and verify only the new expectations fail.
- [ ] **Step 3:** Implement minimal classification/linkage helpers and apply them before event creation.
- [ ] **Step 4:** Run NEWS_FUTURE tests and verify green.

### Task 2: Cluster duplicate news articles into one future event

**Files:**
- Modify: `tests/collectors/test_news_future.py`
- Modify: `src/event_radar/collectors/news_future.py`

**Interfaces:**
- Produces: stable cluster identity based on normalized company, event type, and date window; one `RawEvent` per cluster with `cluster_article_count` in raw payload.

- [ ] **Step 1:** Add a failing test with two outlets and two query payloads describing the same company/event/window; expect one event and count 2.
- [ ] **Step 2:** Run the targeted test and verify RED.
- [ ] **Step 3:** Implement cluster aggregation and cluster-based source UID.
- [ ] **Step 4:** Run targeted and full NEWS_FUTURE tests and verify GREEN.

### Task 3: Live compression verification and cleanup

**Files:**
- Temporary: `.github/workflows/news-future-diagnostic.yml`

**Interfaces:**
- Consumes: real NAVER API HUB secrets.
- Produces: before/after candidate counts and event-type distribution; no persistent generated data.

- [ ] **Step 1:** Run the temporary diagnostic on the feature branch and record before/after counts.
- [ ] **Step 2:** Remove the temporary workflow.
- [ ] **Step 3:** Run the full pytest suite on the cleaned PR head.
- [ ] **Step 4:** Open/update PR with live evidence; do not merge without user authorization.

### Task 4: Refresh public site after merge

**Files:**
- No permanent production-file change required unless trigger plumbing is necessary.

**Interfaces:**
- Consumes: merged main code and existing `Scheduled Event Collection` workflow.
- Produces: updated `data/`, `site/data/`, and GitHub Pages deployment.

- [ ] **Step 1:** Trigger one collection-equivalent main run using a temporary trigger if direct dispatch is unavailable.
- [ ] **Step 2:** Verify collection success, including compressed NEWS_FUTURE count and filtered IPO/CB visible output.
- [ ] **Step 3:** Verify the data commit reaches main and `Deploy GitHub Pages` succeeds.
- [ ] **Step 4:** Remove any temporary trigger and confirm no diagnostic workflow remains.
