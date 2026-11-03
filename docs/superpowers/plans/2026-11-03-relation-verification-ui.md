# Relation Verification UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make relation provenance and verification status visible on the Event Radar dashboard and event detail page.

**Architecture:** Extend the existing `EventSecurity` JSON contract with optional provenance fields, populate them from canonical/manual relations, and render grouped relation cards in the existing static JS/CSS UI. Keep existing backtest and scoring code unchanged.

**Tech Stack:** Python 3.12, Pydantic, pytest, static HTML/CSS/JavaScript, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-11-03-relation-verification-ui.md`

## Global Constraints
- Existing static site architecture only; no frontend framework.
- A/B may be verified; THEME/PROXY/UNMAPPED must never be presented as verified.
- Manual A/B relations show persistent writeback state.
- Existing event/backtest functionality must remain green.

## Review Focus
- Old EventSecurity rows without provenance fields must still export/render.
- Direct event A rows must not be mislabeled as manual writeback.
- THEME and PROXY must remain visibly non-persistent.
- Evidence URLs must be escaped and only rendered when present.
- Mobile layout must collapse cleanly.

---

### Task 1: Extend relation provenance data contract
**Files:** `src/event_radar/models.py`, `src/event_radar/relations.py`, `src/event_radar/export.py`, `tests/test_relation_provenance_export.py`

- [ ] Write failing tests asserting manual/auto relation provenance survives into exported `related_securities` JSON.
- [ ] Run the focused tests and verify failure because provenance fields are missing.
- [ ] Add optional provenance fields to `EventSecurity`, populate them from `Relation`, and serialize them.
- [ ] Run focused tests and verify pass.

### Task 2: Add visible relation verification UI
**Files:** `site/event.html`, `site/js/event-detail.js`, `site/js/app.js`, `site/css/app.css`, `tests/test_relation_ui.py`

- [ ] Write failing static UI tests for grouped relation sections, persistence labels, and dashboard mapping-status text.
- [ ] Run the focused tests and verify failure.
- [ ] Implement relation summary/group rendering and compact dashboard status labels.
- [ ] Add responsive styling for relation cards/status pills.
- [ ] Run focused tests and verify pass.

### Task 3: Regression verification and deployment
**Files:** existing test suite, `ops/run-now.txt`

- [ ] Run the complete pytest suite.
- [ ] Open a PR and merge only after all tests pass.
- [ ] Trigger a fresh Event Radar run so JSON and GitHub Pages use the new contract/UI.
- [ ] Confirm collection, artifact upload, and Pages deploy steps succeed.